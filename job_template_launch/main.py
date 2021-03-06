# Copyright 2017 Google Inc. All rights reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""
The app for the 'frontend' service, which handles cron job requests to
fetch tweets and store them in the Datastore.
"""

import datetime
import logging
import os

from google.appengine.ext import ndb
import twitter
import webapp2

from googleapiclient.discovery import build
from oauth2client.client import GoogleCredentials


class Tweet(ndb.Model):
  """Define the Tweet model."""
  user = ndb.StringProperty()
  text = ndb.StringProperty()
  created_at = ndb.DateTimeProperty()
  tid = ndb.IntegerProperty()
  urls = ndb.StringProperty(repeated=True)


class LaunchJob(webapp2.RequestHandler):
  """Launch the Dataflow pipeline using a job template."""

  def get(self):
    is_cron = self.request.headers.get('X-Appengine-Cron', False)
    # logging.info("is_cron is %s", is_cron)
    # Comment out the following check to allow non-cron-initiated requests.
    if not is_cron:
      return 'Blocked.'
    # These env vars are set in app.yaml.
    PROJECT = os.environ['PROJECT']
    BUCKET = os.environ['BUCKET']
    TEMPLATE = os.environ['TEMPLATE_NAME']

    # Because we're using the same job name each time, if you try to launch one
    # job while another is still running, the second will fail.
    JOBNAME = PROJECT + '-twproc-template'

    credentials = GoogleCredentials.get_application_default()
    service = build('dataflow', 'v1b3', credentials=credentials)

    BODY = {
            "jobName": "{jobname}".format(jobname=JOBNAME),
            "gcsPath": "gs://{bucket}/templates/{template}".format(
                bucket=BUCKET, template=TEMPLATE),
            "parameters": {"timestamp": str(datetime.datetime.utcnow())},
             "environment": {
                "tempLocation": "gs://{bucket}/temp".format(bucket=BUCKET),
                "zone": "us-central1-f"
             }
        }

    dfrequest = service.projects().templates().create(
        projectId=PROJECT, body=BODY)
    dfresponse = dfrequest.execute()
    logging.info(dfresponse)
    self.response.write('Done')


class FetchTweets(webapp2.RequestHandler):
  """Fetch home timeline tweets from the given twitter account."""

  def get(self):

    # set up the twitter client. These env vars are set in app.yaml.
    consumer_key = os.environ['CONSUMER_KEY']
    consumer_secret = os.environ['CONSUMER_SECRET']
    access_token = os.environ['ACCESS_TOKEN']
    access_token_secret = os.environ['ACCESS_TOKEN_SECRET']

    api = twitter.Api(consumer_key=consumer_key,
                      consumer_secret=consumer_secret,
                      access_token_key=access_token,
                      access_token_secret=access_token_secret)

    last_id = None
    public_tweets = None

    # see if we can get the id of the most recent tweet stored.
    tweet_entities = ndb.gql('select * from Tweet order by tid desc limit 1')
    last_id = None
    for te in tweet_entities:
      last_id = te.tid
      break
    if last_id:
      logging.info("last id is: %s", last_id)

    public_tweets = []
    # grab tweets from the home timeline of the auth'd account.
    try:
      if last_id:
        public_tweets = api.GetHomeTimeline(count=200, since_id=last_id)
      else:
        public_tweets = api.GetHomeTimeline(count=20)
        logging.warning("Could not get last tweet id from datastore.")
    except Exception as e:
      logging.warning("Error getting tweets: %s", e)

    # store the retrieved tweets in the datastore
    logging.info("got %s tweets", len(public_tweets))
    for tweet in public_tweets:
      tw = Tweet()
      # logging.info("text: %s, %s", tweet.text, tweet.user.screen_name)
      tw.text = tweet.text
      tw.user = tweet.user.screen_name
      tw.created_at = datetime.datetime.strptime(
          tweet.created_at, "%a %b %d %H:%M:%S +0000 %Y")
      tw.tid = tweet.id
      urls = tweet.urls
      urllist = []
      for u in urls:
        urllist.append(u.expanded_url)
      tw.urls = urllist
      tw.key = ndb.Key(Tweet, tweet.id)
      tw.put()

    self.response.write('Done')


class MainPage(webapp2.RequestHandler):
  def get(self):
    self.response.write('nothing to see.')


app = webapp2.WSGIApplication(
    [('/', MainPage), ('/timeline', FetchTweets),
     ('/launchtemplatejob', LaunchJob)],
    debug=True)
