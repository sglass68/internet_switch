
from datetime import datetime
from flask import Flask, render_template
from flask.ext.mysql import MySQL
import math
import subprocess

TARGET_IP = '192.168.4.16'


DISABLED, ENABLED, UNKNOWN = range(3)
state_names = ['disabled', 'enabled', 'unknown']


'''
mysql
 apt-get install mysql-server
 (enter root password for mysql server)

 mysql -u root -p
 (enter root password for mysql server)

create database itimer;

create user 'itimer'@'localhost' identified by 'itimer';
grant all privileges on 'itimer'.* to 'itimer'@'localhost';

create table record (start datetime(3), end datetime(3), duration int);

create table state (enabled boolean, start datetime(3));

create table credit (created datetime, seconds int);

'''

time_remaining = None


class Internet(object):
    def __init__(self):
        self.state = UNKNOWN

    def GetState(self):
        out = subprocess.check_output(['sudo', 'iptables', '-L', '-n'])
        match = [line for line in out.splitlines() if TARGET_IP in line]
        if [line for line in match if 'DROP' in line]:
            return DISABLED
        return ENABLED

    def CheckState(self):
        self.state = self.GetState()
        return state_names[self.state]

    def SetState(self, state):
        pass


class Database(object):
    def __init__(self, app):
        self.mysql = MySQL()
        self.mysql.init_app(app)
        self.con = self.mysql.connect()
        self.cur = self.con.cursor()

    def GetCredit(self):
        self.cur.execute('select sum(seconds) from credit;')
        rv = self.cur.fetchall()[0][0]
        return rv and int(rv) or 0

    def GetUsage(self):
        self.cur.execute('select sum(duration) from record;')
        rv = self.cur.fetchall()[0][0]
        return rv and int(rv) or 0

    def GetState(self):
        self.cur.execute('select * from state;')
        rv = self.cur.fetchall()
        if not rv:
            return DISABLED, 0
        state, dt = rv[0]
        return state, dt - datetime.now()

class MyServer(Flask):
    def __init__(self, *args, **kwargs):
        super(MyServer, self).__init__(*args, **kwargs)
        self.reset()
        # MySQL configurations
        self.config['MYSQL_DATABASE_USER'] = 'itimer'
        self.config['MYSQL_DATABASE_PASSWORD'] = 'itimer'
        self.config['MYSQL_DATABASE_DB'] = 'itimer'
        self.config['MYSQL_DATABASE_HOST'] = 'localhost'
        self.db = Database(self)

        self.internet = Internet()
        inet_state = self.internet.CheckState()
        credit = self.db.GetCredit()
        debit = self.db.GetUsage()
        self.remaining = credit - debit

        db_state, used = self.db.GetState()
        if db_state:
            self.remaining -= used.total_seconds()
        self.remaining = math.floor(self.remaining)

        self.internet.SetState(db_state)
        self.state = db_state
        print 'Internet is %s, credit remaining %d' % (db_state, self.remaining)


    def reset(self):
        self.string = "hello"


app = MyServer(__name__)

@app.route('/enable')
def enable():
    print "Enabling internet"
    return "nothing"

@app.route('/disable')
def disable():
    print "Disabling internet"
    return "nothing"

@app.route("/")
def main():
    return render_template('index.html', state=app.internet.state, time_remaining=app.remaining)


if __name__ == "__main__":
    app.run(host='192.168.4.1')
