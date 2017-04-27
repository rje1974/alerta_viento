# Copyright (c) 2016 RAMPBA
#
#    Vea el archivo LICENSE.txt para comprender sus derechos.
#
"""Ejemplo de como implementar una alarma en weewx. 

********************************************************************************

Para usar esta alarma, agregue el siguiente código en su archivo de configuración weewx.conf:

[Alarm]
  expression = "outTemp < 40.0"
  time_wait = 3600
  smtp_host = smtp.mymailserver.com
  smtp_user = myusername
  smtp_password = mypassword
  mailto = auser@adomain.com, anotheruser@someplace.com
  from = me@mydomain.com
  subject = "Alarm message from weewx!"
  
En este ejemplo, si la temperatura exterior cae debajo de los 40 F°, se enviara un correo electrónico
a la lista separada por comas especificada en la opcion "mailto", en este caso
auser@adomain.com, another@somewhere.com

El ejemplo asume que su servidor de correo SMTP se encuentra en smtp.mymailserver.com y
que utiliza un logeo seguro (secure logins). Si esto no fuera asi, deje libres las lines
para smtp_user y smtp_password y no se intentara ningun logeo de acceso.

La configuracion del remitente en el correo es opcional. Si Usted no brinda la misma, una de facto sera instroducida; pero
su servidor SMTP puede que no la acepte

La configuracion del valor "asunto" (subjet) en el correo electronico es opcional. Si Usted no brinda la misma, una de facto sera instroducida.

Para evitar una catarata de correos electrónicos, se configuró el valor time_wait para que mande uno cada 3600 segundos (una hora).

********************************************************************************

Para especificar que este nuevo servicio se cargue y sea ejecutador, se debe agregar el mismo a la
configuración (weewx.conf) dentro de la seccion de configuración "report_services", localizada en la sub-sección [Engine][[Services]].

[Engine]
  [[Services]]
    ...
    report_services = weewx.engine.StdPrint, weewx.engine.StdReport, examples.alarm.MyAlarm

********************************************************************************

Si Usted desea usar a la vez este ejemplo de alerta y el ejemplo lowBattery.py, simplemente debera fusionar
las dos opciones de configuracion bajo [Alarm] y agregar los dos servicios a
report_services.

********************************************************************************
"""

import time
import smtplib
from email.mime.text import MIMEText
import threading
import syslog

import weewx
from weewx.engine import StdService
from weeutil.weeutil import timestamp_to_string, option_as_list

# Inherit from the base class StdService:
class MyAlarm(StdService):
    """Custom service that sounds an alarm if an arbitrary expression evaluates true"""
    
    def __init__(self, engine, config_dict):
        # Pass the initialization information on to my superclass:
        super(MyAlarm, self).__init__(engine, config_dict)
        
        # This will hold the time when the last alarm message went out:
        self.last_msg_ts = 0
        
        try:
            # Dig the needed options out of the configuration dictionary.
            # If a critical option is missing, an exception will be raised and
            # the alarm will not be set.
            self.expression    = config_dict['Alarm']['expression']
            self.time_wait     = int(config_dict['Alarm'].get('time_wait', 3600))
            self.smtp_host     = config_dict['Alarm']['smtp_host']
            self.smtp_user     = config_dict['Alarm'].get('smtp_user')
            self.smtp_password = config_dict['Alarm'].get('smtp_password')
            self.SUBJECT       = config_dict['Alarm'].get('subject', "Alarm message from weewx")
            self.FROM          = config_dict['Alarm'].get('from', 'alarm@weewx.com')
            self.TO            = option_as_list(config_dict['Alarm']['mailto'])
            syslog.syslog(syslog.LOG_INFO, "alarm: Alarm set for expression: '%s'" % self.expression)
            
            # If we got this far, it's ok to start intercepting events:
            self.bind(weewx.NEW_ARCHIVE_RECORD, self.newArchiveRecord)    # NOTE 1
            
        except KeyError, e:
            syslog.syslog(syslog.LOG_INFO, "alarm: No alarm set. %s" % e)
            
    def newArchiveRecord(self, event):
        """Gets called on a new archive record event."""
        
        # To avoid a flood of nearly identical emails, this will do
        # the check only if we have never sent an email, or if we haven't
        # sent one in the last self.time_wait seconds:
        if not self.last_msg_ts or abs(time.time() - self.last_msg_ts) >= self.time_wait :
            # Get the new archive record:
            record = event.record
            
            # Be prepared to catch an exception in the case that the expression contains 
            # a variable that is not in the record:
            try:                                                              # NOTE 2
                # Evaluate the expression in the context of the event archive record.
                # Sound the alarm if it evaluates true:
                if eval(self.expression, None, record):                       # NOTE 3
                    # Sound the alarm!
                    # Launch in a separate thread so it doesn't block the main LOOP thread:
                    t  = threading.Thread(target = MyAlarm.soundTheAlarm, args=(self, record))
                    t.start()
                    # Record when the message went out:
                    self.last_msg_ts = time.time()
            except NameError, e:
                # The record was missing a named variable. Write a debug message, then keep going
                syslog.syslog(syslog.LOG_DEBUG, "alarm: %s" % e)

    def soundTheAlarm(self, rec):
        """This function is called when the given expression evaluates True."""
        
        # Get the time and convert to a string:
        t_str = timestamp_to_string(rec['dateTime'])

        # Log it in the system log:
        syslog.syslog(syslog.LOG_INFO, "alarm: Alarm expression \"%s\" evaluated True at %s" % (self.expression, t_str))

        # Form the message text:
        msg_text = "Alarm expression \"%s\" evaluated True at %s\nRecord:\n%s" % (self.expression, t_str, str(rec))
        # Convert to MIME:
        msg = MIMEText(msg_text)
        
        # Fill in MIME headers:
        msg['Subject'] = self.SUBJECT
        msg['From']    = self.FROM
        msg['To']      = ','.join(self.TO)
        
        # Create an instance of class SMTP for the given SMTP host:
        s = smtplib.SMTP(self.smtp_host)
        try:
            # Some servers (eg, gmail) require encrypted transport.
            # Be prepared to catch an exception if the server
            # doesn't support it.
            s.ehlo()
            s.starttls()
            s.ehlo()
            syslog.syslog(syslog.LOG_DEBUG, "  **** using encrypted transport")
        except smtplib.SMTPException:
            syslog.syslog(syslog.LOG_DEBUG, "  **** using unencrypted transport")

        try:
            # If a username has been given, assume that login is required for this host:
            if self.smtp_user:
                s.login(self.smtp_user, self.smtp_password)
                syslog.syslog(syslog.LOG_DEBUG, "  **** logged in with user name %s" % (self.smtp_user,))
            
            # Send the email:
            s.sendmail(msg['From'], self.TO,  msg.as_string())
            # Log out of the server:
            s.quit()
        except Exception, e:
            syslog.syslog(syslog.LOG_ERR, "alarm: SMTP mailer refused message with error %s" % (e,))
            raise
        
        # Log sending the email:
        syslog.syslog(syslog.LOG_INFO, "  **** email sent to: %s" % self.TO)

if __name__ == '__main__':
    """This section is used for testing the code. """
    import sys
    import configobj
    from optparse import OptionParser


    usage_string ="""Usage: 
    
    alarm.py config_path 
    
    Arguments:
    
      config_path: Path to weewx.conf"""
    parser = OptionParser(usage=usage_string)
    (options, args) = parser.parse_args()
    
    if len(args) < 1:
        sys.stderr.write("Missing argument(s).\n")
        sys.stderr.write(parser.parse_args(["--help"]))
        exit()
        
    config_path = args[0]
    
    weewx.debug = 1
    
    try :
        config_dict = configobj.ConfigObj(config_path, file_error=True)
    except IOError:
        print "Unable to open configuration file ", config_path
        exit()
        
    if 'Alarm' not in config_dict:
        print >>sys.stderr, "No [Alarm] section in the configuration file %s" % config_path
        exit(1)
    
    engine = None
    alarm = MyAlarm(engine, config_dict)
    
    rec = {'extraTemp1': 1.0,
           'outTemp'   : 38.2,
           'dateTime'  : int(time.time())}

    event = weewx.Event(weewx.NEW_ARCHIVE_RECORD, record=rec)
    alarm.newArchiveRecord(event)
