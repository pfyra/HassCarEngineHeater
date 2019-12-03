import requests
import json


class HassAPI(object):
    def __init__(self, token):
        #self.token = token
        #url = "https://10.0.3.5:8123/api/error/all"
        self.server = "http://127.0.0.1:8123"
        self.headers = {
#            'Authorization': "Bearer eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJpc3MiOiJhNGE1ZDA4ZTdjOWQ0MzI2YTM5NTM2OGZlOGVhNzkxZSIsImlhdCI6MTU3Mzc2NTU5NCwiZXhwIjoxODg5MTI1NTk0fQ.88N-Y4HGBW-jHfKLz9O9Ni7LfYkdRUn9l9XSPzlZ-Lo",
            'Authorization': "Bearer " + token
        }


    def get_states(self):
        url = self.server + "/api/states"
        response = requests.request('GET', url, headers=self.headers)
        #print(response.text)
        resp = json.loads(response.text)

        #for entity in resp:
        #    #print( entity['entity_id'])
        #    if entity['entity_id'].startswith('switch.'):
        #        print (entity)
        #return ""
        return resp

    def turn_off(self, entity_id):

        data = {
            'entity_id': entity_id
        }

        url = self.server + "/api/services/switch/turn_off"
        response = requests.post(url, headers=self.headers, json=data)
        resp = json.loads(response.text)

        return response.status_code == 200


    def turn_on(self, entity_id):

        data = {
            'entity_id': entity_id
        }

        url = self.server + "/api/services/switch/turn_on"
        response = requests.post(url, headers=self.headers, json=data)
        #resp = json.loads(response.text)
        return response.status_code == 200
