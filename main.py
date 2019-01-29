import traceback
import logging
import time
import threading
import argparse
import configparser
from datetime import (datetime,timedelta)
from threading import Event
from feed import CbFeed, CbFeedInfo, CbReport
from threatconnect import ThreatConnect
from threatconnect.Config.FilterOperator import FilterOperator


logging_format = '%(asctime)s-%(name)s-%(lineno)d-%(levelname)s-%(message)s'
logging.basicConfig(format=logging_format)

logger = logging.getLogger()
logger.setLevel(logging.INFO)


class ThreatConnectConfigurationError(Exception):
    def __init__(self, message):
        self.message = message

class CbThreatConnectConnector(object):

    def __init__(self,access_id,secret_key,default_org,base_url,polling_interval,outfile,niceness=0,debug=False,logfile=None):
        logger.info("base url = {0}".format(base_url))
        self.tcapi = ThreatConnect(api_aid=access_id,api_sec=secret_key,api_url=base_url)
        self.niceness=niceness
        self._debug = debug
        self.logfile = logfile
        self.outfile = outfile
        specs = {"M": "minutes", "W": "weeks", "D": "days", "S": "seconds", "H": "hours"}
        spec = specs[polling_interval[-1].upper()]
        val = int(polling_interval[:-1])
        self.interval = timedelta(**{spec: val})
        self.stopEvent = Event()

    @property
    def debug(self):
        return self._debug

    @debug.setter
    def setDebugMode(self,debugOn):
        self._debug = debugOn
        if self._debug == True:
            logger.setLevel(logging.DEBUG)

    def _PollThreatConnect(self):
        last = None
        while(True):
            if self.stopEvent.isSet():
                logger.info("Threatconnect Connector was signalled to stop...stopping")
                break
            else:
                #poll threat connect if the time delta has passed since the last time we did
                now = datetime.now()
                delta = now - last if last is not None else self.interval
                last = now
                if delta >= self.interval:
                    self.generate_feed_from_threatconnect()
                else:
                    time.sleep(delta.seconds)

    def RunForever(self):
        threading.Thread(target=self._PollThreatConnect).start()

    def generate_feed_from_threatconnect(self):

        reports = []
        # create an Indicators object
        indicators = self.tcapi.bulk_indicators()
        filter1 = indicators.add_filter()

        filter1.add_pf_type('Address', FilterOperator.EQ)
        filter1.add_pf_type('File', FilterOperator.EQ)
        filter1.add_pf_type('Host', FilterOperator.EQ)

        try:
            # retrieve Indicators
            indicators.retrieve()
        except RuntimeError as e:
            print('Error: {0}'.format(e))

        for indicator in indicators:
            score = indicator.rating * 20 #int(row.get('rating', 0)) * 20
            # Many entries are missing a description so I placed this here to default them
            # to the IOC value in the absence of a description.
            title = indicator.description # row.get('description', None)
            #if not title:
            #    title = row.get('summary')
            fields = {'iocs': {},
                      'id': indicator.id,
                      'link': indicator.weblink,
                      'title': title,
                      'score': score,
                      'timestamp': indicator.date_added,
                      }
            # The next few lines are designed to insert the Cb supported IOCs into the record.
            if indicator.type == "File":
                fields['iocs']['md5'] = [indicator.indicator]
            elif indicator.type == "Address":
                fields['iocs']['ipv4'] = [indicator.indicator]
            elif indicator.type == "Host":
                fields['iocs']['dns'] = [indicator.indicator]
            reports.append(CbReport(**fields))

        feedinfo = {'name': 'threatconnect',
                    'display_name': "ThreatConnect",
                    'provider_url': "http://www.threatconnect.com",
                    'summary': "Sends threat intelligence from Threatconnect platform to Carbon Black Response",
                    'tech_data': "There are no requirements to share any data with Carbon Black to use this feed.",
                    'icon': 'threatconnect-logo.png',
                    'category': "Connectors",
                        }

        feedinfo = CbFeedInfo(**feedinfo)
        feed = CbFeed(feedinfo, reports)
        logger.debug("dumping feed...")
        created_feed = feed.dump()

        logger.debug("Writing out feed to disk")
        with open(self.outfile, 'w') as fp:
            fp.write(created_feed)


def main(configfile):
    cfg = verify_config(configfile)
    threatconnectconnector = CbThreatConnectConnector(**cfg)
    threatconnectconnector.RunForever()

def verify_config(config_file):

    cfg = {}

    config = configparser.ConfigParser()
    config.read(config_file)

    if not config.has_section('general'):
        raise ThreatConnectConfigurationError('Config does not have a \'general\' section.')

    if not 'polling_interval' in config['general']:
        raise ThreatConnectConfigurationError("Config does not have an \'polling_interval\' key-value pair.")
    else:
        cfg['polling_interval'] = config['general']['polling_interval']

    if 'niceness' in config['general']:
        #os.nice(int(config['general']['niceness']))
        cfg['niceness'] = int(config['general']['niceness'])

    if 'debug' in config['general']:
        # os.nice(int(config['general']['niceness']))
        cfg['debug'] = bool(config['general']['debug'])

    if not 'logfile' in config['general']:
        raise ThreatConnectConfigurationError("Config does not have an \'logfile\' key-value pair.")
    else:
        cfg['logfile'] = config['general']['logfile']

    if not 'outfile' in config['general']:
        raise ThreatConnectConfigurationError("Config does not have an \'outfile\' key-value pair.")
    else:
        cfg['outfile'] = config['general']['outfile']

    if not 'base_url' in config['general']:
        raise ThreatConnectConfigurationError("Config does not have an \'base_url\' key-value pair.")
    else:
        cfg['base_url'] = config['general']['base_url']

    if not 'secret_key' in config['general']:
        raise ThreatConnectConfigurationError("Config does not have an \'secret_key\' key-value pair.")
    else:
        cfg['secret_key'] = config['general']['secret_key']

    if not 'access_id' in config['general']:
        raise ThreatConnectConfigurationError("Config does not have an \'access_id\' key-value pair.")
    else:
        cfg['access_id'] = config['general']['access_id']

    if not 'default_org' in config['general']:
        raise ThreatConnectConfigurationError("Config does not have an \'default_org\' key-value pair.")
    else:
        cfg['default_org'] = config['general']['default_org']

    return cfg



if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Yara Agent for Yara Connector')
    parser.add_argument('--config-file',
                        required=True,
                        default='yara_agent.conf',
                        help='Location of the config file')

    args = parser.parse_args()
    try:
        main(args.config_file)
    except:
        logger.error(traceback.format_exc())
