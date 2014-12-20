#!/usr/bin/env python
# -*- coding=utf-8 -*-

from optparse import OptionParser
from sqlobject import *
import sys
import os


class Game(SQLObject):
    class sqlmeta:
        table = "game"
    weekend = ForeignKey("Weekend")
    local = UnicodeCol()
    local_score = IntCol()
    visitor = UnicodeCol()
    visitor_score = IntCol()
    date = DateTimeCol()
    place = UnicodeCol()
    verified = BoolCol(default=False)


class Weekend(SQLObject):
    class sqlmeta:
        table = "weekend"
    fch_id = IntCol()
    competition = UnicodeCol()
    day = DateCol()
    num = IntCol()
    completed = BoolCol(default=False)

    game = MultipleJoin("Game", joinColumn="weekend_id")


class FCHDatabase(object):
    def __init__(self, database_name, server, rebuild=False):
        self.conn = connect("sqlite://%s/database.db"
                            % os.path.dirname(os.path.realpath(__file__)))
        if rebuild:
            prepare_db(True)
            #self.grant_access_to_user('jfeliu')

    def grant_access_to_user(self, user):
        tables = [
            "weekend",
            "game"]
        for table in tables:
            self.conn.query("GRANT SELECT ON TABLE %s TO jfeliu" % table)

    @staticmethod
    def create_db(database_name, server):
        return FCHDatabase(database_name, server, rebuild=True)


def connect(connection_string):
    connection = connectionForURI(connection_string)
    sqlhub.processConnection = connection
    return connection


def prepare_db(dropdb=False):
    if dropdb:
        try:
            drop_db()
        except Exception, e:
            print e
    Weekend.createTable()
    Game.createTable()


def drop_db():
    Game.dropTable(ifExists=True)
    Weekend.dropTable(ifExists=True)

if __name__ == '__main__':
    usage = "usage: %prog [options] db_name"
    parser = OptionParser(usage)

    (options, args) = parser.parse_args()

    FCHDatabase.create_db(args[0], 'localhost')
