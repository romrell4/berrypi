"""
Berry client class.
"""
import json
import logging
import socket
import threading

from .state import ClientState
from .. import utilities

# if we are going fixed server and skipping udp, then the
# ip address in berry/utilities.py will get used.
server_ip_address =  0

LIGHT_CHANGE_RATE_THRESHOLD = 4
MAG_CHANGE_RATE_THRESHOLD = 2

# How long to wait between sensor checks
INITIAL_LIGHT_SENSOR_DELAY = 0.1
LIGHT_SENSOR_DELAY = 0.1

INITIAL_MAGNET_SENSOR_DELAY = 0.1
MAGNET_SENSOR_DELAY = 0.1

# How long to wait (in cycles) after a selection before the user can make
# another selection of this widget
SELECTION_DELAY_COUNT = 25




class BerryClient():
    _berry = None
    _port = None
    _code = None
    _responses = None
    _state = None
    _looping = True

    def __init__(self, berry, port):
        self._berry = berry
        self._berry._client = self
        self._port = int(port)
        self._state = ClientState(client=self)
        self._looping = True

        # Maps berry/event handlers to functions, for use in user code
        self._code = {}

        # Maps attribute calls to response values, for use in RemoteBerries
        self._responses = {}

    def package_self_in_json(self):
        output = self._berry._as_json()
        # this is where the port gets set for the server.  mdj 5/20/2019
        # ... it's at github\berrypi\berry\client_for_testing\client.py in
        output['port'] = self._port
        return json.dumps(output)

    def after_found_server (self):
        # Wait for a TCP connection from the server.
        response, _socket = utilities.blocking_receive_from_tcp(self._port)
        server_response = json.loads(response)
        global server_ip_address
        server_ip_address = server_response['ip']
        logging.info('Server IP is {}'.format(server_ip_address))
        # Set up the berry (runs the setup() function)
        self._berry.setup_client()
        # Start the loop() handler loop
        threading.Thread(target=self.main_loop).start()
        return server_response, _socket

    def use_this_server (self, preset_server_IP_address):
        global server_ip_address
        server_ip_address = preset_server_IP_address
        logging.info('Server IP is, hard-coded to be, {}'.format(server_ip_address))
        logging.info('my port is set to {}'.format(self._port))
        # say hello to our hard coded server...
        # might as well send our identity in a json file
        output = self.package_self_in_json()
        output = '{"command":"newberry-via-fixedip", ' \
                 + '"source":"' + utilities.get_my_ip_address() + '",' \
                 + '"berry-body":'+output+'}'
        utilities.send_with_tcp(output,server_ip_address,utilities.SERVER_PORT)
        # listen for the server to respond and then store that socket for
        # future communication.
        return self.after_found_server()

    def find_a_server(self):
        """
        Finds server and initiates handshake.
        """
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)

        output = self.package_self_in_json()

        logging.info('Sending via udp broadcast...\n' + output)

        sock.sendto(
            output.encode('utf-8'),
            ('255.255.255.255', utilities.REGISTRATION_PORT),
        )
        sock.close()
        return self.after_found_server ()

    def wait_for_message(self, tcpsock):
        """
        Waits for messages to come through in TCP. Part of the main client
        loop.
        """
        # Wait for a TCP connection from the server.
        return utilities.blocking_receive_from_tcp(self._port, tcpsock)

    def process_message(self, message):
        """
        Processes an incoming message.
        """
        message = json.loads(message)

        if 'command' not in message:
            logging.error('\n   *** ERROR, message missing command')
            return

        command = message['command']

        if command == 'code-save':
            # Update the code
            if 'code' in message:
                self._berry.update_handler_code(message['code'])

            # And update the name
            if 'name' in message:
                self._berry.save_berry_name(message['name'])

        elif command == 'remote-command':
            # Run the remote command on this client
            attribute = message['attribute']
            source = message['source']
            key = message['key'] if 'key' in message else None
            payload = message['payload'] if 'payload' in message else None

            # Check if the berry object has the attribute
            if hasattr(self._berry, attribute):
                # Yes, the berry has this attribute
                attr = getattr(self._berry, attribute)

                if callable(attr):
                    # Function
                    if payload:
                        # Pass in parameters
                        response = attr(payload)
                    else:
                        # Don't pass in any parameters
                        response = attr()
                else:
                    # Not a function
                    if payload:
                        # Payload, so we're setting the attribute
                        setattr(self._berry, attribute, payload)
                    else:
                        # Not a function
                        response = attr
            else:
                response = None

            # Respond with remote-response message to be relayed to source
            message = {
                'command': 'remote-response',
                'destination': source,
                'response': response,
                'key': key,
            }

            send_message_to_server(message=message)

        elif command == 'event':
            # Look up the code and execute it
            key = message['key']
            code = self.get_code(key)

            if code is not None:
                code()

        elif command == 'remote-response':
            # Parse the response from the remote
            response = message['response']

            if 'error' in response:
                if response['error'] == 'widget-not-found':
                    raise Exception(
                        'Widget {} not found'.format(response['name']),
                    )
                else:
                    raise Exception(
                        'Generic error: {}'.format(response['error']),
                    )
            else:
                key = message['key']

                # Make sure response key exists
                self.create_response_key(key)

                # Add the response to the _responses dictionary
                self.add_response(key, response)

        elif command == 'update-state':
            # Replace the client's state with the new, updated state
            new_state = message['state']
            self._state._replace_state(new_state)

            # And call the on_global_state_change handler
            self._berry.on_global_state_change()

        else:
            # Unrecognized message
            pass

    def main_loop(self):
        """
        Main loop. Calls the loop() handler if it exists.
        """
        # Start main loop thread (loop() handler)
        while True:
            if self._looping:
                # Call loop() handler
                self._berry.loop_client()

    def input_loop(self):
        """
        Debug mode input loop. Processes keyboard input and acts accordingly.
        Make sure to hit enter after each command.

        Usage:
            s -- sends 'berry-selected' message to server
            t -- executes the on_test() handler for the berry
            b -- button press
            r -- button release
            h -- reload handlers
            z -- set state, takes JSON (example: `z { "key": 3290 }`)
        """
        while True:
            command = input('> ').strip()

            if command == 's':
                # Select berry
                self.send_berry_selected_message()
            elif command == 'b':
                # Test: button press
                self._berry.on_press()
            elif command == 'r':
                # Test: button release
                self._berry.on_release()
            elif command == 't':
                # Test code handler
                self._berry.on_test()
            elif command == 'h':
                # Test code handler
                self._berry.reload_handlers()
            elif command == '?':
                # Test code handler
                print('''s -- sends 'berry-selected' message to server
t -- executes the on_test() handler for the berry
b -- button press
r -- button release
h -- reload handlers
z -- set state, takes JSON (example: `z { "key": 3290 }`)
''')
            elif len(command) >= 1 and command[0] == 'z':
                # Test updating state
                json_data = command[1:].strip()
                update = json.loads(json_data)
                self.update_state(update)
            elif command == '':
                # Allow empty input (for spacing apart output)
                pass
            else:
                print('Unrecognized input, please try again\n')

    def send_berry_selected_message(self):
        """
        Sends the berry-selected message to the server. Used in input loop and
        light loop.
        """
        code = self._berry.load_handler_code()

        message = {
            'command': 'berry-selected',
            'code': code,
            'name': self._berry.name,
            'guid': self._berry.guid,
        }

        send_message_to_server(message=message)

    def send_email(self, to, subject, body):
        """
        Sends an email, via the server.
        """
        message = {
            'command': 'send-email',
            'to': to,
            'subject': subject,
            'body': body,
        }

        send_message_to_server(message=message)

    def call_remote_command(self, key, payload=None):
        """
        Calls a remote command, passing in an optional payload. Used by user
        code.
        """
        if key in self.code:
            self.code[key](payload)

    def send_message_to_server(self, message):
        """
        Wrapper for send_message_to_server, to provide easier access.
        """
        send_message_to_server(message)

    def create_response_key(self, key):
        """
        Makes sure key exists in the _responses dictionary.
        """
        if key not in self._responses:
            self._responses[key] = []

    def add_response(self, key, response):
        """
        Adds a response for the given key. (We put it at the front so that pop
        works the way we expect.)
        """
        self._responses[key].insert(0, response)

    def get_response(self, key):
        """
        Gets the key from the _responses dictionary and loops until it can
        pop a response off the queue.
        """
        response = None
        count = 0
        while True:
            try:
                response = self._responses.get(key, []).pop()
                break
            except IndexError:
                pass

            # Avoid an infinite loop (not sure yet if 10,000 is the right
            # number, but it's something to start with)
            count += 1
            if count > 10000:
                break

        return response

    def wipe_user_handlers(self):
        """
        Wipes the _code dictionary, used on initial setup and whenever the
        handlers get reloaded. This way we don't end up with multiple
        registrations for the same thing on the same berry.
        """
        self._code = {}

        # If the berry has handlers, it should have a wipe_handlers() method
        # that unhooks anything the user has set (see button for an example)
        if hasattr(self, 'wipe_handlers'):
            self.wipe_handlers()

    def set_code(self, key, value):
        """
        Sets code for a key. Used in user handlers.
        """
        self._code[key] = value

    def get_code(self, key):
        """
        Returns code for a key. Used in user handlers.
        """
        if key in self._code:
            return self._code[key]
        else:
            return None

    def update_state(self, data):
        """
        Updates the state dictionary with the specified dictionary by sending
        it to the server (the canonical source of state).
        """
        # Send the update delta dictionary to the server
        message = {
            'command': 'update-state',
            'state': data,
        }

        send_message_to_server(message=message)

    def get_state(self):
        """
        Returns the state dictionary.
        """
        return self._state


def send_message_to_server(message):
    # logging.info("Sending message to server: {}".format(message))

    utilities.send_with_tcp(
        json.dumps(message),
        server_ip_address,
        utilities.SERVER_PORT,
    )
