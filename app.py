from flask import Flask, redirect, request, render_template, session
import os
import concurrent.futures
import requests
import time
import datetime
app = Flask(__name__)
app.config['SECRET_KEY'] = 'asdfghjkl'

REDIRECT_URI = 'http://127.0.0.1:5000/callback'

@app.route('/')
def index():
    authorize_url = 'https://accounts.spotify.com/authorize'
    params = {
        'client_id': os.environ['CLIENT_ID'],
        'response_type': 'code',
        'redirect_uri': REDIRECT_URI,
        'scope': 'user-top-read'
    }
    authorization_url = authorize_url + '?' + '&'.join([f'{k}={v}' for k, v in params.items()])

    return redirect(authorization_url)

@app.route('/callback', methods=['GET', 'POST'])
def callback():

    if request.method == 'GET':
        code = request.args.get('code')

    # Exchange the authorization code for an access token
    token_url = 'https://accounts.spotify.com/api/token'
    payload = {
        'grant_type': 'authorization_code',
        'code': code,
        'redirect_uri': REDIRECT_URI,
        'client_id': os.environ['CLIENT_ID'],
        'client_secret': os.environ['CLIENT_SECRET'],
    }
    response = requests.post(token_url, data=payload)


    if response.status_code == 200:
        data = response.json()
        access_token = data['access_token']
        session['access_token'] = access_token
        # Use the access token for further API requests or store it securely
    else:
        print('Error:', response.status_code)
        print('Response:', response.text)


    return redirect('/artist-list?access_token=' + access_token)

@app.route('/artist-list')
def artist_list():
    #access_token = request.args.get('access_token')
    access_token = session.get('access_token')
    url = 'https://api.spotify.com/v1/me/top/artists'
    headers = {
        'Authorization': 'Bearer ' + access_token
    }

    response = requests.get(url, headers=headers)
    if response.status_code == 200:
        data = response.json()
        artist_list = []
        # Extract the artist information from the response
        for artist in data['items']:
            artist_name = artist['name']
            artist_list.append(artist_name)

        session['artist_list'] = artist_list
        if not artist_list:
            artist_list[0] = "No top artists"

        return render_template('artist_list.html', artists=artist_list)
    else:
        print('Error:', response.status_code)
        return None

@app.route('/fetch-concerts', methods=['GET', 'POST'])
def fetch_concerts():
    #artists = request.args.get('artists').split(',')

    artists = session.get('artist_list')
    location = request.form.get('location')
    concert_info = []

    def fetch_events(artist):
        events = search_events(artist, location)
        if events:
            concert_info.extend(events)

    # Create a thread pool with a limited number of worker threads
    max_workers = 5  # Adjust the number of threads as per your needs
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        # Submit API requests as tasks to the thread pool
        futures = [executor.submit(fetch_events, artist) for artist in artists]
        concurrent.futures.wait(futures)

    # Render the HTML template with concert information
    return render_template('artist_list.html', artists=artists, concert_info=concert_info)

def get_coordinates(city):
    api_key = os.environ.get("MAPS_KEY")
    url = "https://maps.googleapis.com/maps/api/geocode/json"

    params = {
        "address": city,
        "key": api_key
    }
    response = requests.get(url, params=params)

    if response.status_code == 200:
        data = response.json()

        if data["status"] == "OK":
            location = data["results"][0]["geometry"]["location"]
            latitude = location["lat"]
            longitude = location["lng"]
            return latitude, longitude
        else:
            print("Error occurred while geocoding:", data["status"])
    else:
        print("Error occurred while geocoding:", response.status_code)

    return None, None

def search_events(artist, location):
    url = 'https://app.ticketmaster.com/discovery/v2/events'
    api_key = os.environ.get("TICKETMASTER_KEY")

    latitude, longitude = get_coordinates(location)
    if latitude is not None and longitude is not None:
        params = {
            'apikey': api_key,
            'keyword': artist,
            "geoPoint": f"{latitude},{longitude}",
            'radius' : 50,
            'unit' : 'miles',
            'classificationName': 'music'
        }
    else:
        params = {
            'apikey': api_key,
            'keyword': artist,
            "city": location,
            'classificationName': 'music'
        }

    response = requests.get(url, params=params)

    if response.status_code == 429:
        # Exponential backoff
        delay = 0.5
        retries = 0
        max_retries = 10

        while response.status_code == 429 and retries < max_retries:
            time.sleep(delay)
            delay *= 2  # Increase the delay exponentially
            response = requests.get(url, params=params)
            retries += 1

    if response.status_code == 200:
        data = response.json()
        if '_embedded' in data:
            events = data['_embedded']['events']

            filtered_events = []
            for event in events:
                event_info = {}
                if 'name' in event:
                    event_info['name'] = event['name']
                else:
                    event_info['name'] = 'TBD'
                if 'dates' in event:
                    event_date = event['dates']['start']['localDate']
                    event_date = datetime.datetime.strptime(event_date, "%Y-%m-%d").strftime("%m/%d/%y")
                    event_info['date'] = event_date
                    if 'localTime' in event['dates']['start']:
                        event_time = event['dates']['start']['localTime']
                        event_time = datetime.datetime.strptime(event_time, "%H:%M:%S").strftime("%H:%M")
                        event_info['time'] = event_time
                    else:
                        event_info['time'] = 'TBD'
                else:
                    event_info['date'] = 'TBD'
                    event_info['time'] = 'TBD'
                if '_embedded' in event:
                    event_info['venue'] = event['_embedded']['venues'][0]['name']
                    event_info['city'] = event['_embedded']['venues'][0]['city']['name']
                    event_info['country'] = event['_embedded']['venues'][0]['country']['name']
                else:
                    event_info['venue'] = 'TBD'
                    event_info['city'] = 'TBD'
                    event_info['country'] = 'TBD'

                event_info['link'] = event['url']

                filtered_events.append(event_info)

            return filtered_events
        else:
            return None
    else:
        print('Error:', response.status_code)
        return None

if __name__ == '__main__':
    app.run()
