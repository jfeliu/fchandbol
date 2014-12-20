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
import sys
import os

URL = 'http://handbol.playoffinformatica.com/peticioAjaxCompeticioPublica.php'
HEADERS = {'Content-Type': 'application/x-www-form-urlencoded'}
CONFIG_FILE = 'local.cfg'
MAX_TWEET_LEN = 140


class ResultsFCH:
    """Class to fetch and tweet results from FCH"""

    def __init__(self, debug=False):
        self.debug = debug

        # Connect to fch_db
        db_dir = os.path.dirname(os.path.realpath(__file__))
        db = os.path.join(db_dir, 'database.db')

        if not os.path.exists(db):
            logging.error("Database not exists: '%s'", db)
            fchmodels.FCHDatabase.create_db(db, 'localhost')
            logging.info("Database '%s' has been created", db)

        fchmodels.connect("sqlite://%s" % db)

        # Load config
        if not os.path.exists(CONFIG_FILE):
            logging.error("Config file not exists: '%s'", CONFIG_FILE)
            sys.exit(1)
        config = ConfigParser.RawConfigParser()
        config.read(CONFIG_FILE)
        print config.defaults()
        self.init_ids = [int(x.strip()) for x in config.defaults()
                         .get('init_ids').split(',')]

        # Connect to twitter
        self.tw_api = twitter.Api(
            consumer_key=config.defaults().get('con_key'),
            consumer_secret=config.defaults().get('con_sec'),
            access_token_key=config.defaults().get('token_key'),
            access_token_secret=config.defaults().get('token_sec'))

    def run(self):
        today = datetime.today().date()
        day = today

        # For all competitions
        for init_id in self.init_ids:
            fch_id = init_id
            while(1):
                # Get completed weekend
                weekend = fchmodels.Weekend.selectBy(fch_id=fch_id,
                                                     completed=True)
                if weekend.count() == 0:
                    payload = {'idJornada': fch_id,
                               'peticioKey':
                               'peticio_competicio_publica_resultats'}

                    # Getting HTML code
                    r = requests.post(URL,
                                    data=payload,
                                    headers=HEADERS)

                    # Parsing HTML elements
                    soup = BeautifulSoup(r.text)
                    competition = soup.findAll('h3')[0].text
                    logging.info('Parsing id "%d", competition "%s"',
                                 fch_id,
                                 competition)
                    num, day = soup.findAll('h4')[0].text.split('/')
                    # Return an error when there is no more
                    # games for this category
                    try:
                        num = int(num.split('Jornada')[-1].strip())
                    except:
                        logging.debug('No more games for this category!')
                        break
                    day = datetime.date(datetime.strptime(day.strip(),
                                                          "%d-%m-%Y"))
                    if today > day + timedelta(weeks=1):
                        fch_id += 1
                        # Break if fch_id in self.init_ids, it will
                        # belongs to another category
                        if fch_id in self.init_ids:
                            logging.debug('Breaking to another category')
                            break
                        logging.debug('Outdated results %s', day)
                        continue
                    elif today < day:
                        logging.debug('Outdated results %s', day)
                        break
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
                            break
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

                    # Get existing but non-completed weekend
                    weekend = fchmodels.Weekend.selectBy(fch_id=fch_id)
                    if weekend.count() == 0:
                        weekend = fchmodels.Weekend(fch_id=fch_id,
                                                    competition=competition,
                                                    day=day,
                                                    num=num,
                                                    completed=completed)
                        weekend_id = weekend.id
                    else:
                        weekend = weekend.getOne()
                    if completed:
                        weekend.set(completed=True)
                    weekend_id = weekend.id

                    new_partits = []
                    for partit in partits:
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
                (u'"ANTONIO LÁZARO"', u''),
                (U'-', u''),
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
                #u'': u'@HandbolSalou',
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
            if len(update) > MAX_TWEET_LEN:
                update = update[:MAX_TWEET_LEN - 3] + '...'
            if self.debug:
                logging.info(update)
            else:
                status = self.tw_api.PostUpdate(update)
                logging.debug(status)
        return 0


if __name__ == '__main__':

    usage = 'usage: %prog [options]'
    parser = OptionParser(usage=usage)

    parser.add_option('-l', '--log-file', dest='log_file',
                      help='Log file.', type=str)
    parser.add_option('-d', '--debug', dest='debug',
                      help='Executes in debug mode.',
                      default=False, action='store_true')

    (options, args) = parser.parse_args()

    if options.debug:
        level = logging.DEBUG
    else:
        level = logging.INFO

    logging.basicConfig(level=level,
                        filename=options.log_file,
                        format="%(asctime)s %(levelname)s %(message)s",
                        datefmt="%Y-%m-%d %H:%M:%S")

    get_results = ResultsFCH(debug=options.debug)
    get_results.run()
