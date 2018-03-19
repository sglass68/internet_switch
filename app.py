
from datetime import datetime
from flask import Flask, render_template
from flask.ext.socketio import SocketIO, emit
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
        print 'Setting internet state to', state


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
        """Get the current internet state, and when that state was set"""
        self.cur.execute('select * from state;')
        rv = self.cur.fetchall()
        if not rv:
            return DISABLED, 0
        state, dt = rv[0]
        return state, dt

    def GetUsed(self):
        """Return the duration of internet that is used but not recorded yet"""
        state, dt = self.GetState()
        if not state:
            return 0, 0
        return 1, math.floor((dt - datetime.now()).total_seconds())

    def RecordEnableTime(self):
        """Record that we have started a new internet session"""
        self.cur.execute('delete from state;')
        self.cur.execute('insert into state (enabled, start) values (true, now());')

    def RecordSession(self):
        """Record that the internet session has ended"""
        state, start = self.GetState()
        if state == DISABLED:
            # We did not write a record at the start of the session, so don't
            # know when it began
            print 'Missing record in "state" table'
            return
        self.cur.execute('insert into record (start, end, duration) values ("%s", now(), %d);'
                         % (start.strftime('%Y-%m-%d %H:%M:%S'), (datetime.now() - start).total_seconds()))


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

        self.config['SECRET_KEY'] = 'secret!'
        self.socketio = SocketIO(self)

        db_state, used = self.db.GetUsed()
        self.remaining -= used

        self.internet.SetState(db_state)
        self.state = db_state
        print 'Internet is %s, credit remaining %d' % (db_state, self.remaining)

    def reset(self):
        self.string = "hello"

    def SetEnable(self, enable):
        if enable == self.state:
            return
        if enable:
            self.db.RecordEnableTime()
            self.internet.SetState(True)
        else:
            self.db.RecordSession()
            self.internet.SetState(False)
        self.state = enable


app = MyServer(__name__)
socketio = SocketIO(app)

def SendState():
    emit('server status', {'state': app.state, 'remaining': app.remaining})

@app.route('/enable')
def enable():
    app.SetEnable(True)
    return ''

@app.route('/disable')
def disable():
    app.SetEnable(False)
    return ''

@socketio.on('connect')
def test_connect():
    print 'Client connected'
    SendState()

@socketio.on('disconnect')
def test_disconnect():
    print 'Client disconnected'

@socketio.on('change')
def change():
    SendState()

@app.route("/")
def main():
    return render_template('index.html')


if __name__ == "__main__":
    socketio.run(app, host='192.168.4.1')
