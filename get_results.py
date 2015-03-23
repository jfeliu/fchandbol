#!/usr/bin/env python
# -*- coding=utf-8 -*-

from datetime import datetime, timedelta
from BeautifulSoup import BeautifulSoup
from optparse import OptionParser
from sqlobject import *
import ConfigParser
import fchmodels
import requests
import logging
import twitter
import pprint
import sys
import os


class ResultsFCH:
    """Class to fetch and tweet results from FCH"""

    URL = 'http://handbol.playoffinformatica.com/peticioAjaxCompeticioPublica.php'
    HEADERS = {'Content-Type': 'application/x-www-form-urlencoded'}
    CONFIG_FILE = 'local.cfg'
    MAX_TWEET_LEN = 140
    STATUS_OUTDATED = u'Outdated results'
    STATUS_FUTURE = u'Results from future'
    STATUS_OTHER_CAT = u'Turning to another category'
    STATUS_NO_MORE_GAMES = u'No more games for this category'
    STATUS_OK = u'OK'
    CATEGORIES = [u'MASTER',
                  u'SENIOR',
                  u'JUVENIL',
                  u'CADET',
                  u'INFANTIL']


    def __init__(self, category, debug=False):
        self.debug = debug

        # Check category
        if category not in self.CATEGORIES:
            logging.error('Wrong category, use one of these: %s',
                          self.CATEGORIES)
            sys.exit()

        # Connect to fch_db
        try:
            fchmodels.connect(os.environ['DB_URL'])
        except Exception, e:
            logging.error(e)
            sys.exit()

        # Load config
        con_key = os.environ[category+'_CON_KEY']
        con_sec = os.environ[category+'_CON_SEC']
        token_key = os.environ[category+'_TOKEN_KEY']
        token_sec = os.environ[category+'_TOKEN_SEC']
        self.init_ids = [int(x.strip()) \
                         for x in os.environ[category+'_INIT_IDS'].split(',')]

        # Connect to twitter
        self.tw_api = twitter.Api(
            consumer_key=con_key,
            consumer_secret=con_sec,
            access_token_key=token_key,
            access_token_secret=token_sec)

    def get_results(self, fch_id):
        """ Fetch results from FCH website. """

        today = datetime.today().date()
        day = today

        payload = {'idJornada': fch_id,
                   'peticioKey': 'peticio_competicio_publica_resultats'}

        results = {}

        # Getting HTML code
        r = requests.post(self.URL,
                          data=payload,
                          headers=self.HEADERS)

        # Parsing HTML elements
        soup = BeautifulSoup(r.text)
        competition = soup.findAll('h3')[0].text
        results['competition'] = competition
        logging.info('Parsing id "%d", competition "%s"',
                     fch_id,
                     competition)
        num, day = [x.strip() for x in soup.findAll('h4')[0].text.split('/')]
        # Return an error when there is no more
        # games for this category
        try:
            num = int(num.split('Jornada')[-1].strip())
            results['num'] = num
        except:
            status = self.STATUS_NO_MORE_GAMES
            logging.warning(status)
            results['status'] = status
            return results

        day = datetime.date(datetime.strptime(day.strip(),
                                              "%d-%m-%Y"))
        results['day'] = day

        if today > day + timedelta(weeks=1):
            fch_id += 1

            # Break if fch_id in self.init_ids, it will
            # belongs to another category
            if fch_id in self.init_ids:
                status = self.STATUS_OTHER_CAT
                logging.warning(status)
                results['status'] = status
                return results

            status = self.STATUS_OUTDATED
            logging.warning(status)
            results['status'] = status
            results['completed'] = True
            return results

        elif today < day:
            status = self.STATUS_FUTURE
            logging.warning(status)
            results['status'] = status
            return results

        local = soup.findAll('td', {'class': 'local'})
        visitant = soup.findAll('td', {'class': 'visitant'})
        gols_local = soup.findAll('td', {'class':
                                            'resultat-local'})
        gols_visitant = soup.findAll('td', {'class':
                                            'resultat-visitant'})
        dia = soup.findAll('td', {'class': 'dia'})
        hora = soup.findAll('td', {'class': 'hora'})
        lloc = soup.findAll('td', {'class': 'lloc'})
        verified = soup.findAll('td', {'class': 'textVerifi'})

        partits = []
        completed = True
        for i in range(len(local)):
            partit = {}
            partit['local'] = local[i].text
            partit['gols_local'] = gols_local[i].text
            partit['visitant'] = visitant[i].text
            partit['gols_visitant'] = gols_visitant[i].text
            if not dia[i].text or hora[i].text == 'Pendent':
                # No data for this match or
                # it is pending to schedule
                continue
            partit['dia'] = datetime.strptime(
                dia[i].text + ' ' + hora[i].text,
                "%d-%m-%Y %H:%M")
            partit['lloc'] = lloc[i].text
            if verified[i].text:
                partit['verified'] = False
                completed = False
            else:
                partit['verified'] = True
            partits.append(partit)
        results['partits'] = partits
        results['completed'] = completed
        results['status'] =self.STATUS_OK

        return results


    def run(self):
        pp = pprint.PrettyPrinter()
        # For all competitions
        for init_id in self.init_ids:
            fch_id = init_id
            while(1):
                # Get completed weekend
                weekend = fchmodels.Weekend.selectBy(fch_id=fch_id,
                                                     completed=True)
                if weekend.count() == 0:
                    # Get results
                    results = self.get_results(fch_id)
                    logging.debug(results)

                    if results['status'] in (self.STATUS_FUTURE,
                                             self.STATUS_OTHER_CAT,
                                             self.STATUS_NO_MORE_GAMES):
                        break

                    # Get existing but non-completed weekend
                    weekend = fchmodels.Weekend.selectBy(fch_id=fch_id)
                    if weekend.count() == 0:
                        # Insert weekend
                        weekend = fchmodels.Weekend(
                            fch_id=fch_id,
                            competition=results['competition'],
                            day=results['day'],
                            num=results['num'],
                            completed=results['completed'])
                        weekend_id = weekend.id
                    else:
                        weekend = weekend.getOne()
                    if results['completed']:
                        weekend.set(completed=True)
                    weekend_id = weekend.id

                    new_partits = []
                    for partit in results.get('partits', []):
                        if partit['gols_local'] and partit['gols_visitant']:
                            old_partit = fchmodels.Game.selectBy(
                                weekend=weekend_id,
                                local=partit['local'],
                                visitor=partit['visitant'])
                            if old_partit.count() == 0:
                                # New match
                                game = fchmodels.Game(
                                    weekend=weekend_id,
                                    local=partit['local'],
                                    local_score=int(partit['gols_local']),
                                    visitor=partit['visitant'],
                                    visitor_score=int(
                                        partit['gols_visitant']),
                                    date=partit['dia'],
                                    place=partit['lloc'],
                                    verified=partit['verified'])
                                new_partits.append(game)
                            else:
                                # Already existing match
                                old_partit = old_partit.getOne()
                                if not old_partit.verified and partit['verified']:
                                    # Not verified match
                                    old_partit.set(verified=int(
                                        partit['verified']))
                                    if old_partit.local_score != int(partit['gols_local']) or old_partit.visitor_score != int(partit['gols_visitant']):
                                        logging.info("Aquest partit ja "
                                                     "existia però no estava "
                                                     "verificat")
                                        old_partit.set(local_score=int(
                                            partit['gols_local']))
                                        old_partit.set(visitor_score=int(
                                            partit['gols_visitant']))
                                        new_partits.append(old_partit)
                    if new_partits:
                        self.notify(new_partits, weekend)
                fch_id += 1
                # Break if fch_id in self.init_ids, it will belongs
                # to another category
                if fch_id in self.init_ids:
                    logging.debug('Breaking to another category')
                    break

    def clean_tweet(self, s):
        repl = [(u'TERCERA', u'3a'),
                (u'CATALANA', u'Cat.'),
                (u'PREFERENT', u'Pref.'),
                (u'PRIMERA', u'1a'),
                (u'MASCULINA', u'Masc.'),
                (u'FEMENINA', u'Fem.'),
                (u'HANDBOL', u'H.'),
                (u'ANTONIO', u'Ant.'),
                (u'CLUB', u'C.')]
        for i in repl:
            s = s.replace(i[0], i[1])
        return s.title()

    def make_hashtag(self, s):
        repl = [(u'PRIMERA', u'1a'),
                (u'SEGONA', u'2a'),
                (u'TERCERA', u'3a'),
                (u'CATALANA', u'Cat'),
                (u'PREFERENT', u'Pref'),
                (u'MASCULINA', u'Masc'),
                (u'FEMENINA', u'Fem'),
                (u'FASE ÚNICA', u''),
                (u'GRUP ÚNIC', u''),
                (u'LLIGA', u'Lliga'),
                (u'FASE', u'Fase'),
                (u'GRUP', u'Grup'),
                (u'SÈNIOR', u'Sèn'),
                (u'MÀSTERS', u'Màsters'),
                (u'JUVENIL', u'Juvenil'),
                (u'INFANTIL', u'Infantil'),
                (u'FEDERACIÓ', u'Fede'),
                (u'SÈRIE', u'Serie'),
                (u'"ANTONIO LÁZARO"', u''),
                (u'COPA', u'Copa'),
                (u'-', u''),
                (u' ', u'')]
        for i in repl:
            s = s.replace(i[0], i[1])
        return u'#' + s

    def get_team_twitter_user(self, team):
        keyword_user = {
                u'HANDBOL GARBÍ DE PALAFRUGELL': u'@c_handbolgarbi',
                u'HANDBOL GARBÍ "B" DE PALAFRUGELL': u'@c_handbolgarbi "B"',
                u'HANDBOL GARBÍ "C" DE PALAFRUGELL': u'@c_handbolgarbi "C"',
                u'CLUB HANDBOL RAPID CORNELLA': u'@HandbolCornella',
                u'CLUB HANDBOL RÁPID CORNELLÁ': u'@HandbolCornella',
                u'CLUB HANDBOL RÀPID CORNELLÀ': u'@HandbolCornella',
                u'A.E. AULA': u'@AEAulaHandbol',
                u'CLUB HANDBOL RIPOLLET': u'@handbolripollet',
                u'CH.CANOVELLES': u'@CHCanovelles',
                u'HANDBOL  TERRASSA': u'@HTerrassa',
                u'HANDBOL TERRASSA': u'@HTerrassa',
                u'HANDBOL COOPERATIVA SANT BOI': u'@CoopeHandbol',
                u'CLUB HANDBOL MARTORELL': u'@CH_Martorell',
                u'CLUB HANDBOL SANT MIQUEL': u'@CHSantMiquel',
                u'SANT MIQUEL, CLUB HANDBOL': u'@CHSantMiquel',
                u'CLUB HANDBOL VIC': u'@HandbolVic',
                u'CLUB ESPORTIU MOLINS DE REI': u'@HandbolMolins',
                u'CEH BCN SANTS UBAE': u'@HandbolBCNSants',
                u'HANDBOL SANT QUIRZE': u'@HSantQuirze',
                u'HANDBOL BORDILS': u'@handbolbordils',
                u'BM POLINYÀ': u'@bmpolinya',
                u'HANDBOL ESPLUGUES': u'@HEsplugues',
                u'HANDBOL POBLENOU': u'@H_Poblenou',
                u'H POBLENOU': u'@H_Poblenou',
                u'CLUB HANDBOL IGUALADA': u'@handboligualada',
                u'CH IGUALADA': u'@handboligualada',
                u'HANDBOL CARDEDEU': u'@CHCardedeu',
                u'CH CARDEDEU': u'@CHCardedeu',
                u'HANDBOL GAVÀ': u'@Clubhandbolgava',
                u'UNIÓ ESPORTIVA HANDBOL CALELLA': u'@UEHCalella',
                u'BM LA ROCA': u'@bmlaroca',
                u'UNIO ESPORTIVA SARRIÀ': u'@UESarria77',
                u'UNIÓ ESPORTIVA SARRIÀ': u'@UESarria77',
                u'KH-7 FBMG. BLANCS I BLAUS GRANOLLERS': u'@BMGranollers',
                u'KH-7 FBMG. GRANOLLERS': u'@BMGranollers',
                u'BM. GRANOLLERS ATLÈTIC': u'@BMGranollers',
                u'BM. GRANOLLERS': u'@BMGranollers',
                u'BLANQUES I BLAVES BM. GRANOLLERS': u'@BMGranollers',
                u'BLANCS I BLAUS BM. GRANOLLERS': u'@BMGranollers',
                u'HANDBOL SANT CUGAT': u'@hstcugat',
                u'H. PALAUTORDERA-SALICRÚ': u'@Chpalau',
                u'H. PALAUTORDERA-SALICRU': u'@Chpalau',
                u'SANT MARTI ADRIANENC': u'@SAdrianenc',
                u'SANT MARTÍ ADRIANENC': u'@SAdrianenc',
                u'HANDBOL BANYOLES': u'@handbolbanyoles',
                u'HC MANYANET': u'@HCManyanet',
                u'HANDBOL CLUB MANYANET': u'@HCManyanet',
                u'GEIEG': u'@HandbolGEiEG',
                }
        for kw in keyword_user:
            if kw in team:
                return team.replace(kw, keyword_user[kw])
        return team

    def notify(self, games, weekend):
        for game in games:
            update = (' Jornada ' + str(weekend.num) + ':\n' +
                        self.get_team_twitter_user(game.local) + ' ' +
                        str(game.local_score) + ' - ' +
                        str(game.visitor_score) + ' ' +
                        self.get_team_twitter_user(game.visitor))
            hashtag = self.make_hashtag(weekend.competition)
            update = hashtag + self.clean_tweet(update)
            if len(update) > self.MAX_TWEET_LEN:
                update = update[:self.MAX_TWEET_LEN - 3] + '...'
            if self.debug:
                logging.info(update)
            else:
                status = self.tw_api.PostUpdate(update)
                logging.debug(status)
        return 0


if __name__ == '__main__':

    usage = 'usage: %prog -c CATEGORY [options]'
    parser = OptionParser(usage=usage)

    parser.add_option('-c', '--category', dest='category',
                      help='Category.', type=str)
    parser.add_option('-l', '--log-file', dest='log_file',
                      help='Log file.', type=str)
    parser.add_option('-d', '--debug', dest='debug',
                      help='Executes in debug mode.',
                      default=False, action='store_true')

    (options, args) = parser.parse_args()

    if not options.category:
        parser.error('Category is mandatory!')
        sys.exit()

    if options.debug:
        level = logging.DEBUG
    else:
        level = logging.INFO

    logging.basicConfig(level=level,
                        filename=options.log_file,
                        format="%(asctime)s %(levelname)s %(message)s",
                        datefmt="%Y-%m-%d %H:%M:%S")

    resultsfch = ResultsFCH(category=options.category.upper(),
                            debug=options.debug)
    resultsfch.run()
