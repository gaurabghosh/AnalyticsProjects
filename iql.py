#
# authors: Ivan Davtchev, Vladimir Markin, Chris Hyams
# last modified date: 2014-11-12 17:30 central time
#

from __future__ import print_function
import pandas as pd

import sys
import collections
import json
import os
import getpass
import re
import requests
from contextlib import closing
from datetime import date, datetime, time
from dateutil.relativedelta import relativedelta
import itertools

from time import sleep

if sys.version_info[0] == 3:
    basestring = str
    from io import StringIO, BytesIO
else:
    from StringIO import StringIO

    BytesIO = StringIO

DEBUG = False

URL_ELABORATABLE = 'https://squall.indeed.com/iql/elaborateable'
URL_ELABORATE = 'https://squall.indeed.com/iql/elaborate'

# looks like 1809 is max for values in at least the companyid case.
# pick a reasonable 1500 default for batching.
# unused (for now)
ELABORATE_BATCH_SIZE = 500

MIN_ELABORATABLE_CHUNK = 1  # we won't split into chunks smaller than this
# in fix_unelaborated

ELABORATE_LIST_STR_MAX = 1710000


class InvalidServerSpecified(Exception):
    MSG = (
        "The URL provided was invalid. If using the 'dataframe()' function, "
        "check that the 'server=' argument is a valid url. (Specific reason "
        "this exception occurred: {specific_reason})"
    )

    def __init__(self, specific_reason):
        self.specific_reason = specific_reason

    def __str__(self):
        return InvalidServerSpecified.MSG.format(specific_reason=self.specific_reason)

    def __repr__(self):
        return InvalidServerSpecified.MSG.format(specific_reason=self.specific_reason)


class IQLWebError(Exception):
    MSG = (
        "Unfortunately, IQL cannot be reached right now. \n"
        "You may run the query/notebook again to see if this was an aberration. \n"
        "Otherwise, please try again in 15 minutes. \n"
        "(Specific reason this exception occurred: {specific_reason})"
    )

    def __init__(self, specific_reason):
        self.specific_reason = specific_reason

    def __str__(self):
        return IQLWebError.MSG.format(specific_reason=self.specific_reason)

    def __repr__(self):
        return IQLWebError.MSG.format(specific_reason=self.specific_reason)


class IQLQueryError(Exception):
    MSG = (
        'Your query resulted in an error response from IQL. '
        'IQL says: "{specific_reason}"'
    )

    def __init__(self, specific_reason):
        self.specific_reason = specific_reason

    def __str__(self):
        return IQLQueryError.MSG.format(specific_reason=self.specific_reason)

    def __repr__(self):
        return IQLQueryError.MSG.format(specific_reason=self.specific_reason)


class IQLSyntaxError(IQLQueryError):
    pass


class IQLInvalidDate(IQLQueryError):
    pass


class IQLUnknownFieldName(IQLQueryError):
    pass


class IQLNoShards(IQLQueryError):
    pass


class IQLDataType(IQLQueryError):
    pass


class IQLNullPointerException(IQLQueryError):
    pass


def _handle_request_error(e):
    IQLWEB_FAILURE = (
        requests.exceptions.ConnectionError,
        requests.exceptions.Timeout,
        requests.exceptions.TooManyRedirects,
        requests.exceptions.ChunkedEncodingError,
    )
    BAD_URL = (
        requests.exceptions.URLRequired,
        requests.exceptions.MissingSchema,
        requests.exceptions.InvalidSchema,
        requests.exceptions.InvalidURL,
    )
    try:
        raise e
    except IQLWEB_FAILURE:
        raise IQLWebError(str(e))
    except BAD_URL:
        raise InvalidServerSpecified(str(e))


def _handle_bad_status(e, response_text):
    try:
        msg = json.loads(response_text)['message']
    except ValueError:
        msg = response_text.split('\n')[0]
        debug_out(msg)
    except Exception:
        msg = str(e)

    if msg == 'No shards':
        raise IQLNoShards(msg)

    elif msg == 'java.lang.NullPointerException':
        raise IQLNullPointerException(msg)

    elif any(('Unknown field' in msg,
              'does not contain expected field' in msg)):
        raise IQLUnknownFieldName(msg)

    elif any(('Query parsing failed' in msg,
              'Syntax error' in msg,
              re.search(r'.*expected.*(found|encountered).*', msg))):
        raise IQLSyntaxError(msg)

    elif any(('Start date has to be before the end date' in msg,
              'Illegal time range' in msg)):
        raise IQLInvalidDate(msg)

    elif any(('A non integer value specified for an integer field' in msg,
              'does not contain expected string field' in msg)):
        raise IQLDataType(msg)

    else:
        raise IQLQueryError(msg)


def debug_out(s):
    if DEBUG:
        print('\t[iql] {}'.format(s))


# NOTE: &json=1 yields tsv results on success and json on failure. go figure.
def get_results(url, params=None, timeout=None, max_size=None):
    if DEBUG:
        debug_out('get_results({}, {})'.format(url, params))

    params['json'] = 1

    try:
        r = requests.post(url, data=params, timeout=timeout, stream=True)
    except requests.exceptions.RequestException as e:
        _handle_request_error(e)
    if DEBUG:
        debug_out('r.ok = %s' % r.ok)
    try:
        r.raise_for_status()
    except requests.exceptions.HTTPError as e:
        _handle_bad_status(e, r.text)
    else:
        size = 0
        content_buffer = BytesIO()
        for chunk in r.iter_content(2048):
            size += len(chunk)
            if max_size is not None and size > max_size:
                raise ValueError("IQL response data is too large.")
            content_buffer.write(chunk)
        text = content_buffer.getvalue()
        if DEBUG:
            debug_out('r.text = {}'.format(text.encode('utf-8')))
        return text


def get_dataframe(url, params=None, column_names=None, timeout=None, max_size=None):
    if DEBUG:
        debug_out('get_dataframe({}, {}, {})'.format(url, params, column_names))

    results = get_results(url, params, timeout=timeout, max_size=max_size)
    df = pd.read_csv(
        BytesIO(results), sep='\t', quoting=3, header=None, encoding='utf-8', names=column_names)
    if column_names:
        df.columns = column_names
    return df


def dataframe(query_string, server='https://squall.indeed.com/iql/',
              header=True, clean=False, tuple=False, username=None, client=None,
              timeout=(2 * 60, 5 * 60), # (resolve timeout, read timeout)
              max_size=None):
    if not server.endswith('/'):
        server += '/'
    iql_server_url_query = server + 'query'
    # iql2 split doesn't return the /* */ for renaming columns since by default
    # iql2 doesn't respect the /* */ syntax
    iql_server_url_split = 'https://squall.indeed.com/iql/split'

    if not username:
        username = os.environ.get("IQL_USER", getpass.getuser())

    if not client:
        client = os.environ.get("IQL_APPNAME")
        if client is not None and re.match(r'ishbook-(.*)', client):
            # just pass 'ishbook' as the client,
            # and include the notebook and whatever other information
            # provided in a comment.
            try:
                client = "analytics-ishbook"
                # query_string += "/* origin: {origin} */".format(origin=m.group(1))
                # Removed this behavior until we can figure out a way to prevent it
                # from breaking existing queries.
            except IndexError:
                pass

    params = {'sync': 'sync', 'q': query_string, 'username': username, 'client': client}

    if 'NOTEBOOK_AUTHOR' in os.environ:
        params['author'] = os.environ['NOTEBOOK_AUTHOR']
    if 'NOTEBOOK_NAME' in os.environ:
        params['clientProcessName'] = os.environ['NOTEBOOK_NAME']
    if 'NOTEBOOK_ID' in os.environ:
        params['clientProcessId'] = os.environ['NOTEBOOK_ID']
    if 'NOTEBOOK_EXECUTION_ID' in os.environ:
        params['clientExecutionId'] = os.environ['NOTEBOOK_EXECUTION_ID']

    # Add support for iqlv2. We have to change the base-url and add the v=2 keyword
    # So that the query parser works
    if 'iql2' in server:
        params['v'] = 2

    if re.match(r'^desc(ribe)?', query_string, flags=re.IGNORECASE):
        js = json.loads(
            get_results(iql_server_url_query, params, timeout=timeout, max_size=max_size))

        if re.search(r'\.', query_string):
            # field description
            # topTerms[], imhotepType, type, name, description
            if not len(js['topTerms']):
                # create a blank top term so we don't return an empty dataframe
                js['topTerms'] = ['', ]

            df = pd.DataFrame.from_dict(js)
        else:
            fields = pd.DataFrame.from_dict(js['fields'])
            metrics = pd.DataFrame.from_dict(js['metrics'])

            # add column specifying data type
            fields['data_type'] = ['field'] * len(fields)
            metrics['data_type'] = ['metric'] * len(metrics)

            # combine, and replace NaN with ''
            df = pd.concat([fields, metrics])
            df.fillna('', inplace=True)

    elif header:
        # get the names of the fields and buckets to use as column names
        try:
            r = requests.post(iql_server_url_split, data=params, timeout=timeout)
        except requests.exceptions.RequestException as e:
            _handle_request_error(e)
        try:
            r.raise_for_status()
        except requests.exceptions.HTTPError as e:
            _handle_bad_status(e, r.text)

        js = json.loads(r.text)

        # clean bucket names, floatscale
        # this might not work with multiple buckets?
        groupby_cleaned = js['groupBy']
        groupby_cleaned = re.sub(r'floatscale?\([^,]+,[^,]+,[^\)]+\)', 'floatscale',
                                 groupby_cleaned)
        groupby_cleaned = re.sub(r'buckets?\([^,]+,[^,]+,[^\)]+\)', 'bucket', groupby_cleaned)

        func_args_pattern = r'\([^),]+,[^)]+\)'
        groupby_cleaned = re.sub(func_args_pattern, '', groupby_cleaned)
        select_cleaned = re.sub(func_args_pattern, '', js['select'])

        column_names = []

        for groupby_part in groupby_cleaned.split(','):
            column_names.append(groupby_part.strip())

        for select_part in select_cleaned.split(','):
            column_names.append(select_part.strip())

        df = get_dataframe(iql_server_url_query, params=params, column_names=column_names,
                           timeout=timeout, max_size=max_size)

    else:
        # dataframe without header (no fancy column names)
        df = get_dataframe(iql_server_url_query, params=params, timeout=timeout, max_size=max_size)

    if clean and 'iql2' in server:
        for column in filter(lambda x: x.lower().startswith('time'), df.columns):
            # If the dataframe is empty, we can't use .iloc[0], so first check if it has data.
            if len(df) > 0 and df[column].iloc[0].startswith('['):
                # In iql2, we can group by TIME(1mo) which we don't want to strip the first character off of
                # keep only beginning of the bucket
                df[column] = df[column].str.split(',').map(lambda x: x[0][1:])
    elif clean:
        # keep the old behavior for queries using ish cell magic.
        df[df.columns[0]] = df[df.columns[0]].str.split(',').map(lambda x: x[0][1:])

    elif tuple:
        # split bucket to [begin,end] list
        df[df.columns[0]] = df[df.columns[0]].str[1:-1].map(lambda x: x.split(','))

    return df


# returns a list of elaboratable fields
def elaboratable():
    try:
        r = requests.get(URL_ELABORATABLE)
    except requests.exceptions.RequestException as e:
        _handle_request_error(e)
    try:
        r.raise_for_status()
    except requests.exceptions.HTTPError as e:
        _handle_bad_status(e, r.text)
    return r.json()


def _iql_with_retries(q, retries, server, sleep_time=5.0):
    try:
        return dataframe(q, server=server)
    except:
        if retries > 0:
            sleep(sleep_time)
            return _iql_with_retries(q, retries - 1, server, sleep_time)
        else:
            raise


def _get_closable(file_obj_or_name):
    if isinstance(file_obj_or_name, basestring):
        return open(file_obj_or_name, 'w+')
    return file_obj_or_name


def _write_chunks(f, chunks, base_query, retries, to_csv_opts, server):
    for i, chunk in enumerate(chunks):
        if len(chunk) == 1:
            chunk = tuple(list(chunk) + [chunk[0]])  # Hack to support single
            # element chunks.
        iql_query = base_query % (str(chunk))
        batch_data = _iql_with_retries(q=iql_query, retries=retries, server=server)
        if i == 0:
            batch_data.to_csv(f, header=True, **to_csv_opts)
        else:
            batch_data.to_csv(f, header=False, **to_csv_opts)


def batch_iql(base_query,
              id_list,
              data_file=None,
              batch_size=5000,
              retries=2,
              to_csv_opts=None,
              server='https://squall.indeed.com/iql/'):
    """
    Takes a base_query, which has a blank %s for string insertion of a long list,
    and iteratively calls IQL, appending data to the same file upon each iteration
    (Adapted from Online Marketing's Python Utilities library)

    Args:
        base_query (str): The IQL query, with a '%s' where the id list chunks
            should be substituted into.
        id_list (list): The list of ids that need to be broken up into chunks.
        data_file [Optional(str or file-like object)]: Filepath or file-like
            object to write the intermediate dataframes to. If not specified,
            defaults to a newly-created StringIO object.
        batch_size [Optional(int)]: The chunk size, [0, 20000]. Default 5000
        retries [Optional(int)]: The number of times to retry a query that
            raises an exception, [0, 8]. Default 2.
        to_csv_opts [Optional(dict)]: Additional options to pass to to_csv().
            Defaults to { "index": False, "encoding": "utf-8" }.

    Returns:
        (File-like Object or str): Returns the value of data_file, if this was
            explicitly passed in. Otherwise returns a StringIO object with
            the contents of the dataframes.
    """

    chunks = [tuple(id_list[i:i + batch_size])
              for i
              in xrange(0, len(id_list), batch_size)]

    if to_csv_opts is None:
        to_csv_opts = {
            "index": False,
            "encoding": "utf-8",
        }

    if data_file is None:
        data_file = StringIO()

    if "header" in to_csv_opts:
        raise ValueError("invalid option 'header' in to_csv_opts")

    if retries < 0 or retries > 8:
        raise ValueError("'retries' must be between 0 and 8, inclusive")

    if batch_size < 0 or batch_size > 20000:
        raise ValueError("'batch_size' must be between 0 and 20000, inclusive")

    if '%s' not in base_query:
        raise ValueError("Query string is missing '%s'.")

    if not isinstance(data_file, basestring):
        try:
            data_file.close
        except AttributeError:
            raise ValueError(
                "data_file must be a filepath or file-like object")

    if isinstance(data_file, basestring):
        with open(data_file, 'w+') as f:
            _write_chunks(f, chunks, base_query, retries, to_csv_opts, server=server)
            f.flush()
            os.fsync(f)
            return data_file  # filepath
    else:
        _write_chunks(data_file, chunks, base_query, retries, to_csv_opts, server=server)
        return data_file  # file-like object


def fix_unelaborated(field, elaborated, ids):
    if len(elaborated) <= MIN_ELABORATABLE_CHUNK:
        return elaborated
    for (e, i) in itertools.izip(elaborated, ids):
        if e == i:
            left = get_elaborated(field, ids[:len(ids) / 2])
            right = get_elaborated(field, ids[len(ids) / 2:])
            return left + right
    return elaborated


def get_elaborated(field, values):
    if DEBUG:
        debug_out('get_elaborated({}, {})'.format(field, values))

    if len(values):
        try:
            values = map(lambda x: str(int(float(x))), values)
        except ValueError:
            pass
    if DEBUG:
        debug_out('converted values: {}'.format(values))

    value_str = '~'.join(values)
    params = {'field': field.lower(), 'list': value_str}

    try:
        r = requests.post(URL_ELABORATE, data=params)
    except requests.exceptions.RequestException as e:
        _handle_request_error(e)
    try:
        r.raise_for_status()
    except requests.exceptions.HTTPError as e:
        _handle_bad_status(e, r.text)
    if DEBUG:
        debug_out('r.ok = %s' % r.ok)
        debug_out('r.text = {}'.format(r.text.encode('utf-8')))
    return fix_unelaborated(field, r.json(), values)


def _get_elaborate_chunks(values):
    # ELABORATE_LIST_STR_MAX

    str_len = lambda x: len('~'.join([str(int(float(y))) for y in x]))
    if str_len(values) > ELABORATE_LIST_STR_MAX:
        for chunk in _get_elaborate_chunks(values[:len(values) / 2]):
            yield chunk
        for chunk in _get_elaborate_chunks(values[len(values) / 2:]):
            yield chunk
    else:
        yield values


# args:
#   field name
#   values to elaborate. may be single value or list, int or string.
#
# returns:
#   list of elaborated values.
#
# notes:
#   it looks like 1809 is the max number of values in at least the companyid case.
#   uses a reasonable 1500 default and batches calls to get complete results.
def elaborate(field, values):
    # if values is a string or not iterable, it needs to be a collection
    if isinstance(values, (str, unicode)) or not isinstance(values, collections.Iterable):
        values = (values,)

    # convert all values to strings
    values = [isinstance(v, (str, unicode)) and v or str(v) for v in values]

    if not len(values):
        return []

    chunks = _get_elaborate_chunks(values)

    return list(
        itertools.chain.from_iterable(
            [get_elaborated(field.lower(), chunk) for chunk in chunks]))


def parse_relative_date(value):
    """Parses an IQL relative date.

    Args:
        value (str): The string value to parse.

    Returns:
        datetime.datetime: A datetime object corresponding to the relative
                            date given.
    """
    if value is None or value.strip() == '':
        raise ValueError('A relative date cannot be empty or be whitespace.')

    lowercase_value = value.lower()
    if 'yesterday'.startswith(lowercase_value):
        return get_start_of_day(date.today() - relativedelta(days=1))
    elif 'today'.startswith(lowercase_value):
        return get_start_of_day(date.today())
    elif 'tomorrow'.startswith(lowercase_value):
        return get_start_of_day(date.today() + relativedelta(days=1))

    _pp = PeriodParser()
    period_delta = _pp.parse_string(value)
    if period_delta is None:
        raise ValueError('Invalid relative date.')
    return get_start_of_day(datetime.now()) - period_delta


class FieldIndex(object):
    """Enum for the index for each field in a relative date
    """
    YEARS = 1
    MONTHS = 2
    WEEKS = 3
    DAYS = 4
    HOURS = 5
    MINUTES = 6
    SECONDS = 7


def get_start_of_day(date_time):
    """Helper method that returns a datetime corresponding to 00:00, given a
    datetime.

    Args:
        date_time (datetime.datetime): a python datetime object

    Returns:
        datetime.datetime: A datetime object corresponding to the beginning of
                            the input datetime.
    """
    return datetime.combine(date_time, time())


class PeriodParser(object):
    """Takes a string period value and returns a Period object that the string
    represents.
    Only first symbol of each field tag is mandatory, the rest of the tag is
    optional. e.g. 1d = 1 day
    Spacing between the numbers and tags is optional. e.g. 1d = 1 d
    Having a tag with no number implies quantity of 1. e.g. d = 1d
    'ago' suffix is optional.
    Commas can optionally separate the period parts.

    Ported from com.indeed.imhotep.sql.parser.PeriodParser
    """

    _pattern = '^(\\s*(\\d+)?\\s*y(?:ear)?s?\\s*,?\\s*)?' \
               '(\\s*(\\d+)?\\s*mo(?:nth)?s?\\s*,?\\s*)?' \
               '(\\s*(\\d+)?\\s*w(?:eek)?s?\\s*,?\\s*)?' \
               '(\\s*(\\d+)?\\s*d(?:ay)?s?\\s*,?\\s*)?' \
               '(\\s*(\\d+)?\\s*h(?:our)?s?\\s*,?\\s*)?' \
               '(\\s*(\\d+)?\\s*m(?:inute)?s?\\s*,?\\s*)?' \
               '(\\s*(\\d+)?\\s*s(?:econd)?s?\\s*)?' \
               '(?:ago)?\\s*$'

    def parse_string(self, value):
        """Parses a string that represents a period.

        Args
            value (str): string to parse

        Returns
            (dateutil.relativedelta): Period object in form of relativedelta
        """
        lowercase_value = value.lower()
        match = re.match(self._pattern, lowercase_value)
        if match is None:
            return None
        years = self._get_value_from_match(match, FieldIndex.YEARS)
        months = self._get_value_from_match(match, FieldIndex.MONTHS)
        weeks = self._get_value_from_match(match, FieldIndex.WEEKS)
        days = self._get_value_from_match(match, FieldIndex.DAYS)
        hours = self._get_value_from_match(match, FieldIndex.HOURS)
        minutes = self._get_value_from_match(match, FieldIndex.MINUTES)
        seconds = self._get_value_from_match(match, FieldIndex.SECONDS)
        return relativedelta(years=years, months=months, weeks=weeks, days=days,
                             hours=hours, minutes=minutes, seconds=seconds)

    @classmethod
    def _get_value_from_match(cls, matcher, i):
        """Gets the numeric value from a matched field (e.g. the number of
        days or hours).

        Args
            matcher:
            i: The index of the field

        """
        field_match = matcher.group((i * 2) - 1)
        if field_match is None or field_match == '':
            return 0
        value = matcher.group(i * 2)
        try:
            return int(value)
        except ValueError:
            # if there is a field match then it is treated as 1 by default
            return 1
