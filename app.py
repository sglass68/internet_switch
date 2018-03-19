
import cros_subprocess
from datetime import datetime
from flask import Flask, render_template
from flask.ext.socketio import SocketIO, emit
from flask.ext.mysql import MySQL
import math
from multiprocessing import Process, Value
import subprocess
from threading import Timer, Thread

TARGET_IP = '192.168.4.16'
DUMP_IP = '192.168.4.7'
#DUMP_IP = TARGET_IP
TIMER_PERIOD = 3

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

# Records all usage of the internet
create table record (start datetime(3), end datetime(3), duration int);

# Records when the Internet was turned on (so we know how much has been used
# since then)
create table state (enabled boolean, start datetime(3));

# Records all credits given for Internet (e.g. to credit an hour a day, add a
# record here wth seconds 3600 at the start of each day)
create table credit (created datetime, seconds int);

'''

time_remaining = None


class Internet(object):
    """Manages the internet connection

    Properties:
        state: Current state of the internet (DISABLED, ENABLED, UNKNOWN)
    """
    def __init__(self):
        self.state = UNKNOWN

    def GetState(self):
        """Get the current state of the internet

        Returns:
            State, as detected by firewall inspection
        """
        # If we see a DROP line for the target IP then the internet is off.
        out = subprocess.check_output(['sudo', 'iptables', '-L', '-n'])
        match = [line for line in out.splitlines() if TARGET_IP in line]
        if [line for line in match if 'DROP' in line]:
            return DISABLED
        return ENABLED

    def CheckState(self):
        """Check the current state

        Returns:
            Internet state (ENABLED, DISABLED, UNKNOWN)
        """
        self.state = self.GetState()
        return self.state

    def SetState(self, state):
        """Set the state of the internet

        Args:
            state: New state to set
        """
        print 'Setting internet state to', state
        # TODO: Implement this


class Database(object):
    """Handles communication with the mysql database"""
    def __init__(self, app):
        self.mysql = MySQL()
        self.mysql.init_app(app)
        self.con = self.mysql.connect()
        self.cur = self.con.cursor()

    def GetCredit(self):
        """Get the total credits added

        Returns:
            Total credits added, in seconds
        """
        self.cur.execute('select sum(seconds) from credit;')
        rv = self.cur.fetchall()[0][0]
        return rv and int(rv) or 0

    def GetUsage(self):
        """Get the total internet usage according to the database

        Returns:
            Total usage in seconds
        """
        self.cur.execute('select sum(duration) from record;')
        rv = self.cur.fetchall()[0][0]
        return rv and int(rv) or 0

    def GetState(self):
        """Get the current internet state, and when that state was set

        A state change is written to the 'state' table when the Internet is
        enabled. It is removed when the Internet is disabled. So if there is
        a state record, we know that the Internet was enabled at some point.

        Returns:
            tuple:
                State (DISABLED or ENABLED)
                Time of last state change (0 if disabled)
        """
        self.cur.execute('select * from state;')
        rv = self.cur.fetchall()
        if not rv:
            return DISABLED, 0
        state, dt = rv[0]
        return state, dt

    def GetUsed(self):
        """Return the duration of internet that is used but not recorded yet

        Returns:
            Duration in seconds since the Internet was started
        """
        state, dt = self.GetState()
        if not state:
            return 0, 0
        return 1, math.floor((datetime.now() - dt).total_seconds())

    def RecordEnableTime(self):
        """Record that we have started a new internet session"""
        self.cur.execute('delete from state;')
        self.cur.execute('insert into state (enabled, start) values (true, now());')
        self.con.commit()

    def RecordSession(self):
        """Record that the internet session has ended"""
        state, start = self.GetState()
        if state == DISABLED:
            # We did not write a record at the start of the session, so don't
            # know when it began
            print 'Missing record in "state" table'
            return
        cmd = ("insert into record (start, end, duration) values ('%s', now(), %d);"
                         % (start.strftime('%Y-%m-%d %H:%M:%S'), (datetime.now() - start).total_seconds()))
        self.cur.execute(cmd)
        self.cur.execute('delete from state;')
        self.con.commit()

    def GetRemaining(self):
        """Get the remaining internet time in seconds

        This totals all credits, subtracts all usage and also subtracts any
        pending usage (the time since the Internet was started).

        Returns:
            Remaining time in seconds
        """
        credit = self.GetCredit()
        debit = self.GetUsage()
        db_state, used = self.GetUsed()
        return credit - debit - used


class MyServer(Flask):
    """This is the Flash server"""
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
        self.remaining = self.db.GetRemaining()

        self.config['SECRET_KEY'] = 'secret!'
        self.socketio = SocketIO(self)

        db_state, used = self.db.GetUsed()

        # If the database thinks the internet is off, check if it really is
        if not db_state:
            db_state = inet_state
            # The internet is on, so record NOW as the time that this session
            # started.
            if inet_state:
                self.db.RecordEnableTime()
        self.internet.SetState(db_state)
        self.state = db_state
        print 'Internet is %s, credit remaining %d' % (db_state, self.remaining)

    def reset(self):
        pass

    def SetEnable(self, enable):
        """Set the Internet to enabled or disabled

        Args:
            enable: desired new state (ENABLED or DISABLED)
        """
        if enable == self.state:
            return
        if enable:
            self.db.RecordEnableTime()
            self.internet.SetState(True)
        else:
            self.db.RecordSession()
            self.internet.SetState(False)
        self.state = enable
        self.UpdateRemaining()

    def UpdateRemaining(self):
        """Update the amount of remaining Internet time"""
        self.remaining = self.db.GetRemaining()


app = MyServer(__name__)
socketio = SocketIO(app)
packets = Value('i', 0)

def SendState():
    """Tell the UI about the new state"""
    socketio.emit('server status',
         {'state': app.state,
          'remaining': app.remaining,
          'packets': packets.value / TIMER_PERIOD,
          'active': '(in use)' if packets.value > 20 else '(idle)'})

@socketio.on('connect')
def test_connect():
    print 'Client connected'
    SendState()

@socketio.on('disconnect')
def test_disconnect():
    print 'Client disconnected'

@socketio.on('set enable')
def set_enable(state):
    """Handle a call from the UI to enable/disable the Internet"""
    enable = state['enable']
    app.SetEnable(enable)
    SendState()

@app.route("/")
def main():
    """This is our main page"""
    return render_template('index.html')

def SendUpdate():
    """Timer function to send an update to the UI"""
    app.UpdateRemaining()
    if app.remaining < 0:
        app.SetEnable(DISABLED)
    SendState()
    packets.value = 0   # Reset the packet count for next time

class PerpetualTimer():
    """A handy class for a repeating timer"""
    def __init__(self,t,hFunction):
        self.t=t
        self.hFunction = hFunction
        self.thread = Timer(self.t,self.handle_function)

    def handle_function(self):
        self.hFunction()
        self.thread = Timer(self.t,self.handle_function)
        self.thread.start()

    def start(self):
        self.thread.start()

    def cancel(self):
        self.thread.cancel()


def StartServer():
    """Start the Flask server along with an update timer for the UI"""
    PerpetualTimer(TIMER_PERIOD, SendUpdate).start()
    socketio.run(app, host='192.168.4.1')

def WatchOutput(stream, lines):
    """Called when we get output from our tcpdump"""
    # Count the number of lines in this output, which equals the number of
    # network packets detected
    packets.value += lines.count('\n')

def Monitor():
    """Process to watch Internet traffic"""
    args = ['sudo', 'tcpdump', '-i', 'eth0', 'host', DUMP_IP, 'and', 'udp',
            '-n']
    pipe = cros_subprocess.Popen(args)
    # Call WatchOutput() with any output
    pipe.CommunicateFilter(WatchOutput)
    pipe.wait()


def MainProgram():
    """Main program with two processes: a Flask server and a packet watcher"""
    server = Process(target=StartServer)
    monitor = Process(target=Monitor)
    server.start()
    monitor.start()
    server.join()
    monitor.join()


if __name__ == "__main__":
    MainProgram()
