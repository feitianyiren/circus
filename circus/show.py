import errno
import signal
import time

from circus.fly import Fly
from circus import logger
from circus import util


class Show(object):

    def __init__(self, name, cmd, num_flies=5, warmup_delay=1.,
                 working_dir=None, shell=False, uid=None,
                 gid=None, send_hup=False, env=None):
        self.name = name
        self.num_flies = int(num_flies)
        self.warmup_delay = warmup_delay
        self.cmd = cmd
        self._fly_counter = 0
        self.stopped = False

        if not working_dir:
            # working dir hasn't been set
            working_dir = util.get_working_dir()

        self.working_dir = working_dir

        self.flies = {}
        self.shell = shell
        self.uid = uid
        self.gid = gid
        self.env = env
        self.send_hup = send_hup

    def __len__(self):
        return len(self.flies)

    def reap_flies(self):
        if self.stopped:
            return

        for wid, fly in self.flies.items():
            if fly.poll() is not None:
                self.flies.pop(wid)

    def manage_flies(self):
        if self.stopped:
            return

        if len(self.flies.keys()) < self.num_flies:
            self.spawn_flies()

        flies = self.flies.keys()
        flies.sort()
        while len(flies) > self.num_flies:
            wid = flies.pop(0)
            fly = self.flies.pop(wid)
            self.kill_fly(fly)

    def spawn_flies(self):
        for i in range(self.num_flies - len(self.flies.keys())):
            self.spawn_fly()
            time.sleep(self.warmup_delay)

    def spawn_fly(self):
        self._fly_counter += 1
        fly = Fly(self._fly_counter, self.cmd, wdir=self.working_dir,
                  shell=self.shell, uid=self.uid, gid=self.gid, env=self.env)
        logger.info('running %s fly [pid %d]' % (self.name, fly.pid))
        self.flies[self._fly_counter] = fly

    # TODO: we should manage more flies here.
    def kill_fly(self, fly):
        logger.info("kill fly %s" % fly.pid)
        fly.stop()

    def kill_flies(self):
        for wid in self.flies.keys():
            try:
                fly = self.flies.pop(wid)
                self.kill_fly(fly)
            except OSError, e:
                if e.errno != errno.ESRCH:
                    raise

    def send_signal_child(self, wid, pid, signum):
        wid = int(wid)
        if wid in self.flies:
            fly = self.flies[wid]
            return fly.send_signal_child(int(pid), signum)
        else:
            return "error: fly not found"

    def send_signal_children(self, wid, signum):
        wid = int(wid)
        if wid in self.flies:
            fly = self.flies[wid]
            return fly.send_signal_children(signum)
        else:
            return "error: fly not found"

    def stop(self):
        if self.stopped:
            return

        self.stopped = True
        self.kill_flies()
        logger.info('%s stopped' % self.name)

    def start(self):
        if not self.stopped:
            return

        self.stopped = False
        self.manage_flies()
        logger.info('%s started' % self.name)

    def restart(self):
        self.stop()
        self.start()
        logger.info('%s restarted' % self.name)

    #################
    # show commands #
    #################

    def handle_status(self, *args):
        if self.stopped:
            return "stopped"
        return "active"

    def handle_stop(self, *args):
        self.stop()
        return "ok"

    def handle_start(self, *args):
        self.start()
        return "ok"

    def handle_restart(self, *args):
        self.restart()
        return "ok"

    def handle_flies(self, *args):
        return ",".join([str(wid) for wid in self.flies.keys()])

    def handle_numflies(self, *args):
        return str(self.num_flies)

    def handle_info(self, *args):
        if len(args) > 0:
            wid = int(args[0])
            if wid in self.flies:
                fly = self.flies[wid]
                return fly.info()
            else:
                return "error: fly '%s' not found" % wid
        else:
            return "\n".join([fly.info() for _, fly in self.flies.items()])

    def handle_quit(self, *args):
        if len(args) > 0:
            wid = int(args[0])
            if wid in self.flies:
                try:
                    fly = self.flies.pop(wid)
                    self.kill_fly(fly)
                    return "ok"
                except OSError, e:
                    if e.errno != errno.ESRCH:
                        raise
            else:
                return "error: fly '%s' not found" % wid
        else:
            self.stop()
            return "ok"

    handle_kill = handle_quit

    def handle_reload(self, *args):
        if self.send_hup:
            for wid, fly in self.flies.items():
                logger.info("SEND HUP to %s [%s]" % (wid, fly.pid))
                fly.send_signal(signal.SIGHUP)
        else:
            for i in range(self.num_flies):
                self.spawn_fly()
            self.manage_flies()
        return "ok"

    handle_hup = handle_reload

    def handle_ttin(self, *args):
        self.num_flies += 1
        self.manage_flies()
        return str(self.num_flies)

    def handle_ttou(self, *args):
        self.num_flies -= 1
        self.manage_flies()
        return str(self.num_flies)

    def handle_kill_child(self, wid, pid):
        return self.send_signal_child(wid, pid, signal.SIGKILL)

    def handle_quit_child(self, wid, pid):
        return self.send_signal_child(wid, pid, signal.SIGQUIT)

    def handle_children(self, wid):
        wid = int(wid)
        if wid in self.flies:
            fly = self.flies[wid]
            return fly.children()
        else:
            return "error: fly not found"

    def handle_signal_fly(self, wid, sig):
        try:
            signum = getattr(signal, "SIG%s" % sig.upper())
        except AttributeError:
            return "error: unknown signal %s" % sig

        wid = int(wid)
        if wid in self.flies:
            fly = self.flies[wid]
            fly.send_signal(signum)
            return "ok"
        else:
            return "error: fly not found"

    def handle_kill_children(self, wid):
        return self.send_signal_children(wid, signal.SIGKILL)

    def handle_quit_children(self, wid):
        return self.send_signal_children(wid, signal.SIGQUIT)
