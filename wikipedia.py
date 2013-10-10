import requests
import lxml.html
import json
import re
from datetime import datetime
from collections import Counter

EDIT_STATS_URL = 'http://vs.aka-online.de/cgi-bin/wppagehiststat.pl'

LANGUAGES = ['en', 'fr', 'ar', 'es', 'de']
WIKI_LINK_PATTERN = '(\w+).wikipedia.org/wiki/(\w+)'


def get_languages():
    """ Returns the list of all languages available in Wikipedia """
    search_page = lxml.html.parse(EDIT_STATS_URL)
    languages = set(l.text.replace('.wikipedia', '') for l in search_page.xpath('//option')
                 if l.text.endswith('.wikipedia'))
    return languages

def get_locales(page, language):
    """ Returns a dictionnary: {'language' : 'Localized_Name', ...} """

    # TODO: Use "http://en.wikipedia.org/w/api.php?action=query&prop=langlinks&titles=Morocco&format=json"
    wiki_url = 'http://{}.wikipedia.org/wiki/{}'.format(language, page)
    wiki_content = requests.get(wiki_url).text
    wiki_page = lxml.html.fromstring(wiki_content)
    other_pages = wiki_page.xpath('//div[@id="p-lang"]//li/a')

    locales = dict()
    locales[language] = page
    for link in other_pages:
        # Ignoring the "Edit links" link
        if not 'hreflang' in link.attrib:
            continue

        lang = link.attrib['hreflang']
        name = link.attrib['title'].encode('utf-8')
        locales[lang] = name
    return locales

GEOLOC_API = 'http://api.ipinfodb.com/v3/ip-country/'
GEOLOC_API_KEY = 'afe9369daa7954f25bfcfd8c45c8454b1290212be93dfc4036cf788957dabbe3'

IP_PATTERN = '^(25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?).(25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?).(25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?).(25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)$'

# Initializing the ip cache
with open('ip_cache', 'r') as ip_cache_file:
    try:
        IP_CACHE = json.loads(ip_cache_file.read())
    except ValueError:
        # If the cache is empty
        IP_CACHE = dict()

def ip_geoloc(ip):
    if ip in IP_CACHE:
        return IP_CACHE[ip]

    try:
        r = requests.get(GEOLOC_API, params=dict(key=GEOLOC_API_KEY, ip=ip, format='json'))
        geoloc_info = json.loads(r.content)
    except requests.exceptions.ConnectionError:
        print "Couldn't connect to the geoloc API for: '{}'".format(ip)
        return None
    except ValueError:
        return None

    # Saving the IP cache for further use
    IP_CACHE[ip] = geoloc_info
    with open('ip_cache', 'w+') as ip_cache_file:
        ip_cache_file.write(json.dumps(IP_CACHE, indent=2, sort_keys=True))

    return geoloc_info

MINUTES_TO_DAY = 1.0 / (24*60)
def normalize_interval(interval):
    """ Takes an interval like: "08:30 m" or "23 d" and returns it as a number of hours"""
    num_tokens = map(float, interval.split(' ')[0].split(':'))
    normalized = None
    if interval.endswith('m'):
        minutes = num_tokens[0] + num_tokens[1] / 60.0
        normalized = minutes / 60.0
    elif interval.endswith('h'):
        minutes = num_tokens[1] + num_tokens[0] * 60
        normalized = minutes / 60.0
    elif interval.endswith('d'):
        normalized = num_tokens[0] * 24.0
    
    if normalized:
        return round(normalized, 2)
    else:
        # If we can't interpret the interval
        return ''

class Wikipage(object):

    def __init__(self, page, language, lang_set=LANGUAGES):
        self.main_locale = language, page

        # Caching stats to avoid superfluous network requests
        self.views_cache = dict()
        # [{'date' : date, 'en' : ... , ...}]
        self.edits_cache = list()
        # [contrib1, contrib2, ...]
        self.contributors_cache = list()

        # Additional comments added to the report
        self.comment = str()

        # We check if the wikipedia page actually exists
        self.valid = requests.head('http://{}.wikipedia.org/wiki/{}'.format(language, page)).status_code != 404

        self.locales = dict()
        self.lang_set = list()
        if self.valid:
            self.locales = get_locales(page, language)
            # We ignore the languages in the langset for which we didn't find any locale
            self.lang_set = [lang for lang in lang_set if lang in self.locales]


    def format_chart(self, stats):
        """ Method to make the stats usable by the 'Morris' js visualization library """
        ykeys = [lang for lang in self.lang_set]
        labels = ['"{}" ({})'.format(self.locales[lang], lang) for lang in self.lang_set]
        return dict(data=stats, xkey='date', ykeys=ykeys, labels=labels)

    def format_donut(self, stats):
        data = list()
        for lang in self.lang_set:
            # Sum of the views for that language
            views = sum(stat[lang] if lang in stat else 0 for stat in stats)
            label = '"{}" ({})'.format(self.locales[lang], lang)
            data.append(dict(label=label, value=views))
        return dict(data=data)


    def daily_views(self, month=datetime.now().month, year=datetime.now().year):
        """ Daily views during the given month """

        # If the views are already cached, we use them directly
        if (month, year) in self.views_cache:
            return self.format_chart(self.views_cache[(month, year)])

        # Otherwise we retrieve the data:
        month_stats = dict()
        month_stats['date'] = '{}-{:02}'.format(year, month)
        stats = dict()

        for language in self.lang_set:

            # Preparing a URL like: http://stats.grok.se/json/fr/201308/Maroc
            formated_date = '{}{:02}'.format(year, month)
            stats_url = 'http://stats.grok.se/json/{}/{}/{}'.format(language, formated_date, self.locales[language])
            views_report = json.loads(requests.get(stats_url).text)

            for views_date, views_num in views_report['daily_views'].iteritems():
                if not views_date in stats:
                    stats[views_date] = dict()
                stats[views_date][language] = views_num

        stats_summary = list()
        for day, daily_stats in stats.iteritems():
            day_summary = {lang : views for lang, views in daily_stats.iteritems()}
            day_summary['date'] = day
            stats_summary.append(day_summary)

        # We cache the result
        self.views_cache[(month, year)] = stats_summary

        return self.format_chart(stats_summary)

    def aggregate_daily_views(self, month, year):
        """Summarizing the daily views into monthly views"""
        if not (month, year) in self.views_cache:
            self.daily_views(month, year)

        monthly_stats = Counter()
        for stat in self.views_cache[(month, year)]:
            for attr, views in stat.iteritems():
                if attr == 'date':
                    continue
                monthly_stats[attr] += views

        monthly_stats = dict(monthly_stats)
        monthly_stats['date'] = '{}-{}'.format(year, month)

        return monthly_stats

    def monthly_views(self, months=[(datetime.now().month, datetime.now().year)]):
        stats = list()

        for month, year in months:
            # We fetch the daily views to exploit their result
            self.daily_views(month, year)

            # We aggregate them using the relevant method
            month_stats = self.aggregate_daily_views(month, year)
            stats.append(month_stats)

        return self.format_chart(stats)

    def views_donut(self, month=datetime.now().month, year=datetime.now().year, days=30):
        # We fetch the daily views of the last 30 days to exploit their result
        month_stats = self.views_period(days=days)

        return self.format_donut(month_stats)

    def monthly_edits(self):
        if self.edits_cache and self.contributors_cache:
            return self.format_chart(self.edits_cache)

        stats = dict()
        contributors = list()
        for language in self.lang_set:
            post_data = dict(lang='{}.wikipedia'.format(language), page=self.locales[language])
            stats_html = requests.post(EDIT_STATS_URL, data=post_data).text
            stats_page = lxml.html.fromstring(stats_html)

            # Monthly edits
            monthly_edits_rows = stats_page.xpath('//th[.="Month"]/../../tr')[1:]
            for row in monthly_edits_rows:
                columns = row.xpath('./td')

                date_tokens = columns[0].text.split('/')
                month, year = date_tokens
                edit_date = '{}-{}'.format(year, month)

                edits_num = int(columns[1].text)

                # Adding the monthly edits to the stats
                if edit_date not in stats:
                    stats[edit_date] = dict()
                stats[edit_date][language] = edits_num

            # Getting the 30 first contributors for the current language
            monthly_contributors_rows = stats_page.xpath('//th[.="User"]/../../tr')[1:]
            for row in monthly_contributors_rows[:30]:
                columns = row.xpath('./td')

                user = dict()
                user_node = columns[0].xpath('a')[0]
                user['username'] = user_node.text
                user['user_link'] = user_node.attrib['href']
                user['edits'] = int(columns[1].text)
                user['edits_percentage'] = round(float(columns[3].text.rstrip('%'))/100.0, 4)
                user['last_edit'] = columns[5].text

                user['edits_interval'] = normalize_interval(columns[6].text) if len(columns[6].text) > 1 else ''

                # Skipping irrelevant contributors
                if user['username'] is None or (user['edits'] < 3 and len(contributors) > 15):
                    continue

                geoloc = None
                if re.match(IP_PATTERN, user['username']):
                    # Geolocalizing the IP
                    geoloc = ip_geoloc(user['username'])
                
                if geoloc is not None:
                    user['country_name'] = geoloc['countryName'].capitalize()
                    user['country_code'] = geoloc['countryCode']
                else:
                    # TODO : Geoloc users that have profiles on Wikipedia
                    user['country_name'] = user['country_code'] = ''

                contributors.append(user)

        # Sorting contributors
        contributors = sorted(contributors, key = lambda c : c['edits'])

        # Formating the edits stats in the 'Morris' (JS lib) style
        stats_summary = list()
        for date, lang_stats in stats.iteritems():
            month_summary = {lang : edits for lang, edits in lang_stats.iteritems()}
            month_summary['date'] = date
            stats_summary.append(month_summary)

        # We cache the result
        self.edits_cache = stats_summary
        self.contributors_cache = contributors

        return self.format_chart(stats_summary)

    def contributors(self):
        # We fetch monthly edits (which will build a list of contributors)
        if not self.contributors_cache:
            self.monthly_edits()

        return self.contributors_cache

    def month_total_views(self, month, year):
        month_views = self.aggregate_daily_views(month, year)        
        return sum(views for attr, views in month_views.iteritems() if attr != 'date')

    def monthly_views_evolution(self, day=datetime.now().day, month=datetime.now().month, year=datetime.now().year):
        # TODO : Fix this ! It doesn't work as expected (won't take the same number of days, for instance)
        p_m, p_y = (month - 1, year) if month > 1 else (12, year - 1)

        # We take the views for the latest 60 days, and take the evolution of the average 
        views = self.views_period(day, month, year, 60)
        later_views = sum(sum(attr for key, attr in stat.iteritems() if key != 'date') for stat in views[:30]) / 30.
        early_views = sum(sum(attr for key, attr in stat.iteritems() if key != 'date') for stat in views[30:]) / 30.

        return 0 if early_views == 0 else (later_views - early_views) / early_views

    def views_period(self, day=datetime.now().day, month=datetime.now().month, year=datetime.now().year, days=30):
        """ Gives the views in a period of time """
        date_str = '{:04d}-{:02d}-{:02d}'.format(year, month, day)

        # Fetching views for the given month
        self.monthly_views([(month, year)])
        views = [data for data in self.views_cache[(month, year)] if data['date'] <= date_str]
        # If we don't have enough views data, we keep adding data from previous months
        while len(views) < days:
            month, year = (month - 1, year) if month > 1 else (12, year - 1)
            self.monthly_views([(month, year)])
            views += self.views_cache[(month, year)]

        # Sorting views and only taking the desired number of days
        views = sorted(views, key = lambda x : x['date'], reverse=True)
        return views[:days]


    # TODO : remove all self.format_chart() calls... make things cleaner!
    def views_period_chart(self, day=datetime.now().day, month=datetime.now().month, year=datetime.now().year, days=30):
        return self.format_chart(self.views_period(day, month, year, days))

if __name__ == "__main__":
    # Unit tests:

    maroc_wiki = Wikipage('Maroc', 'fr')
    # print maroc_wiki.monthly_views_evolution()
    # print maroc_wiki.monthly_views()
    # print maroc_wiki.daily_views()
    # print maroc_wiki.monthly_edits()
    # print maroc_wiki.monthly_edits()
