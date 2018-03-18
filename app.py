
from flask import Flask, render_template
from flask.ext.mysql import MySQL

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

create table record (start DATETIME(3), end DATETIME(3));

create table state (enabled boolean, start datetime(3));

'''

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
        print 'Internet is %s' % state_names[self.state]

class MyServer(Flask):
    def __init__(self, *args, **kwargs):
        super(MyServer, self).__init__(*args, **kwargs)
        self.reset()
        # MySQL configurations
        self.config['MYSQL_DATABASE_USER'] = 'itimer'
        self.config['MYSQL_DATABASE_PASSWORD'] = 'itimer'
        self.config['MYSQL_DATABASE_DB'] = 'itimer'
        self.config['MYSQL_DATABASE_HOST'] = 'localhost'
        mysql = MySQL()
        mysql.init_app(self)

        self.internet = Internet()
        self.internet.CheckState()


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
    return render_template('index.html')


if __name__ == "__main__":
    app.run(host='192.168.4.1')
