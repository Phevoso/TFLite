# python3
#
# Copyright 2019 The TensorFlow Authors. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""Example using TF Lite to detect objects with the Raspberry Pi camera."""

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function


from AWSIoTPythonSDK.MQTTLib import AWSIoTMQTTClient
from pymongo import MongoClient
import argparse
import io
import re
import time
import json
import pprint

from annotation import Annotator

import numpy as np
import picamera

from PIL import Image
from tflite_runtime.interpreter import Interpreter

CAMERA_WIDTH = 640
CAMERA_HEIGHT = 480


# Custom MQTT message callback
def customCallback(client, userdata, message):
    print("Received a new message: ")
    print(message.payload)
    print("from topic: ")
    print(message.topic)
    print("--------------\n\n")


def load_labels(path):
  """Loads the labels file. Supports files with or without index numbers."""
  with open(path, 'r', encoding='utf-8') as f:
    lines = f.readlines()
    labels = {}
    for row_number, content in enumerate(lines):
      pair = re.split(r'[:\s]+', content.strip(), maxsplit=1)
      if len(pair) == 2 and pair[0].strip().isdigit():
        labels[int(pair[0])] = pair[1].strip()
      else:
        labels[row_number] = pair[0].strip()
  return labels


def set_input_tensor(interpreter, image):
  """Sets the input tensor."""
  tensor_index = interpreter.get_input_details()[0]['index']
  input_tensor = interpreter.tensor(tensor_index)()[0]
  input_tensor[:, :] = image


def get_output_tensor(interpreter, index):
  """Returns the output tensor at the given index."""
  output_details = interpreter.get_output_details()[index]
  tensor = np.squeeze(interpreter.get_tensor(output_details['index']))
  return tensor 

def detect_objects(interpreter, image, threshold):
  """Returns a list of detection results, each a dictionary of object info."""
  set_input_tensor(interpreter, image)
  interpreter.invoke()

  # Get all output details
  boxes = get_output_tensor(interpreter, 0)
  classes = get_output_tensor(interpreter, 1)
  scores = get_output_tensor(interpreter, 2)
  count = int(get_output_tensor(interpreter, 3))

  results = []
  for i in range(count):
    if scores[i] >= threshold:
      result = {
          'bounding_box': boxes[i],
          'class_id': classes[i],
          'score': scores[i]
      }
      results.append(result)
  return results


def annotate_objects(annotator, results, labels):
  """Draws the bounding box and label for each object in the results."""
  for obj in results:
    # Convert the bounding box figures from relative coordinates
    # to absolute coordinates based on the original resolution
    ymin, xmin, ymax, xmax = obj['bounding_box']
    xmin = int(xmin * CAMERA_WIDTH)
    xmax = int(xmax * CAMERA_WIDTH)
    ymin = int(ymin * CAMERA_HEIGHT)
    ymax = int(ymax * CAMERA_HEIGHT)

    # Overlay the box, label, and score on the camera preview
    annotator.bounding_box([xmin, ymin, xmax, ymax])
    annotator.text([xmin, ymin],
                   '%s\n%.2f' % (labels[obj['class_id']], obj['score']))
    
def findPoints(coordinates):
    
    for coordinate in coordinates :
    
        ymin = coordinate[0]
        xmin = coordinate[1]
        ymax = coordinate[2]
        xmax = coordinate[3]
        
        x = xmin / xmax
        y = ymin / ymax
        
        point = [x,y]
        
        return point
    
def findLabels(results, labels):
    
    for result in results :
    
        class_id = result.get('class_id')
        
        label = labels[class_id]
        
        return label
    
    
def findScore(results, labels):
    
    for result in results :
    
        score= result.get('score')
        
        return score
    
    
def main():
    
  AllowedActions = ['publish']


  parser = argparse.ArgumentParser(formatter_class=argparse.ArgumentDefaultsHelpFormatter)
  parser.add_argument('--model', help='File path of .tflite file.', required=True)
  parser.add_argument('--labels', help='File path of labels file.', required=True)
  parser.add_argument('--threshold', help='Score threshold for detected objects.', required=False, type=float, default=0.4)
  
  parser.add_argument("-e", "--endpoint", action="store", required=True, dest="host", help="Your AWS IoT custom endpoint")
  parser.add_argument("-r", "--rootCA", action="store", required=True, dest="rootCAPath", help="Root CA file path")
  parser.add_argument("-c", "--cert", action="store", dest="certificatePath", help="Certificate file path")
  parser.add_argument("-k", "--key", action="store", dest="privateKeyPath", help="Private key file path")
  parser.add_argument("-p", "--port", action="store", dest="port", type=int, help="Port number override")
  parser.add_argument("-w", "--websocket", action="store_true", dest="useWebsocket", default=False,
                        help="Use MQTT over WebSocket")
  parser.add_argument("-id", "--clientId", action="store", dest="clientId", default="sensorPub",
                        help="Targeted client id")
  parser.add_argument("-t", "--topic", action="store", dest="topic", default="home", help="Targeted topic")
  parser.add_argument("-m", "--mode", action="store", dest="mode", default="publish",
                        help="Operation modes: %s"%str(AllowedActions))
  parser.add_argument("-M", "--message", action="store", dest="message", default="Hello World!",
                        help="Message to publish")
  parser.add_argument("-d", "--dbMongo", action="store", required=True, dest="dbMongo", 
                        help="Provide the mongoDB client key to store sensor data",)

  args = parser.parse_args()

  labels = load_labels(args.labels)
  interpreter = Interpreter(args.model)
  interpreter.allocate_tensors()
  _, input_height, input_width, _ = interpreter.get_input_details()[0]['shape']

  args = parser.parse_args()
  host = args.host
  rootCAPath = args.rootCAPath
  certificatePath = args.certificatePath
  privateKeyPath = args.privateKeyPath
  port = args.port
  clientId = args.clientId
  topic = args.topic
  useWebsocket = args.useWebsocket
  
  if args.mode not in AllowedActions:
    parser.error("Unknown --mode option %s. Must be one of %s" % (args.mode, str(AllowedActions)))
    exit(2)

  if args.useWebsocket and args.certificatePath and args.privateKeyPath:
    parser.error("X.509 cert authentication and WebSocket are mutual exclusive. Please pick one.")
    exit(2)

  if not args.useWebsocket and (not args.certificatePath or not args.privateKeyPath):
    parser.error("Missing credentials for authentication.")
    exit(2)

  # Port defaults
  if args.useWebsocket and not args.port:  # When no port override for WebSocket, default to 443
    port = 443
  if not args.useWebsocket and not args.port:  # When no port override for non-WebSocket, default to 8883
    port = 8883
      

  #Connect to AWS IoT Core
  myMQTTClient = AWSIoTMQTTClient("rpi-camera") #random key, if another connection using the same key is opened the previous one is auto closed by AWS IOT
  myMQTTClient.configureEndpoint(host, port)
  myMQTTClient.configureCredentials(rootCAPath, privateKeyPath, certificatePath)
  myMQTTClient.configureOfflinePublishQueueing(-1) # Infinite offline Publish queueing
  myMQTTClient.configureDrainingFrequency(2) # Draining: 2 Hz
  myMQTTClient.configureConnectDisconnectTimeout(10) # 10 sec
  myMQTTClient.configureMQTTOperationTimeout(5) # 5 sec
  print ('Initiating Realtime Data Transfer From Raspberry Pi...')
  myMQTTClient.connect()

  with picamera.PiCamera(
      resolution=(CAMERA_WIDTH, CAMERA_HEIGHT), framerate=30) as camera:
#     camera.start_preview()
    try:
      stream = io.BytesIO()
      annotator = Annotator(camera)
      for _ in camera.capture_continuous(
          stream, format='jpeg', use_video_port=True):
        stream.seek(0)
        image = Image.open(stream).convert('RGB').resize(
            (input_width, input_height), Image.ANTIALIAS)
        start_time = time.monotonic()
        results = detect_objects(interpreter, image, args.threshold)
        boxes = get_output_tensor(interpreter, 0)
        elapsed_ms = (time.monotonic() - start_time) * 1000

        annotator.clear()
        annotate_objects(annotator, results, labels)
        annotator.text([5, 0], '%.1fms' % (elapsed_ms))
        annotator.update()

        stream.seek(0)
        stream.truncate()
        
        #Prepare data to semd
        
        coordinates = boxes.tolist()
        
        point = findPoints(coordinates)
        
        label = findLabels(results,labels)
        
        score = findScore(results, labels)
        
        #Publish data to AWS IoT  ymin, xmin, ymax, xmax 
        post = {
          "Sensor Name":"CameraPi",
          "Score":str(score),
          "Coordinates":point,
          "Class_ID":str(label)
        }
        
        pprint.pprint(post)
        
        messageJSON= json.dumps(post)
        myMQTTClient.publish(topic, messageJSON, 1)

        time.sleep(1)

    finally:
      camera.stop_preview()


if __name__ == '__main__':
  main()
