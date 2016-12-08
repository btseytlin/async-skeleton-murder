import asyncio
import websockets
import uuid
import signal
import functools 
import skeletons
import concurrent
import random
import logging
import sys
from logging.handlers import RotatingFileHandler
HOST ='localhost'
PORT = 8765

logger = logging.getLogger('skeleton_fighting')
logger.setLevel(logging.DEBUG)

formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')

# create console handler and set level to debug
ch = logging.StreamHandler()
ch.setLevel(logging.INFO)
logger.addHandler(ch)

fh = RotatingFileHandler('skeleton.log', maxBytes=3e7, backupCount=5, encoding='utf-8')
fh.setLevel(logging.DEBUG)
fh.setFormatter(formatter)
logger.addHandler(fh)

class ClientAlreadyExistsException(Exception):
    pass

class ClientNotRegisteredInRoomException(Exception):
    pass

class SystemMessage():
    valid_msg_types = [
        'registered', #client.uid, client.username
        'joined_room', #room.uid, room.name
        'client_joined_room', #client.uid, client.username,
        'client_left_room', #client.uid, client.username,
        'username_prompt',
        'username_invalid',
        'validation_error'
    ]

    def __init__(self, emitter = None, msg_type = None, args=None, targets=None):
        self.emitter = emitter 
        self.msg_type = msg_type
        self.args = args
        self.targets = targets

class GameSystemMessage(SystemMessage):
    valid_msg_types = [
            "creature_took_damage",
            "creature_health_report",
            "creature_blocked_damage",
            "creature_changed_state",
            "creature_death",
            "creature_action_interrupted",
            "creature_attack_started",
            "creature_attack_finished",
            "creature_def",
            "creature_no_def",
            "creature_start",
            "ai_new_target",
            "ply_notify",

            'ui_setup_creature' #creature.uid, creature.name, creature.alive, creature.max_health, creature.health, creature.target, creature.state
            ]


class Message():
    def __init__(self, author = None, text = None, targets = None):
        self.author = author 
        self.text = text
        self.targets = targets

class Client():
    def __init__(self,  uid=None,websocket=None,username=None, room=None, player=None):
        self.websocket = websocket
        self.username = username
        self.room = room
        self.player = player
        self.uid = uid or str(uuid.uuid4())[:8]

    @property
    def chat_name(self):
        return self.username

    def __repr__(self):
        return 'client|'+self.uid+'|'+self.username


class Room():
    chat_name = 'GLOBAL'
    room_type = 'generic'
    room_actions = []
    def __init__(self, server=None, loop=None, messages = None, clients = None, uid = None, _name = None):
        self.server = server
        self.loop = loop or asyncio.get_event_loop()
        self.messages = messages or []
        self.clients = clients or set()
        self.uid = uid or str(uuid.uuid4())[:8]
        self._name = _name or None
        logger.debug('Initialized room: {} {}'.format(self.room_type, self._name))

    @property
    def name(self):
        return self._name

    @name.setter
    def name(self, val):
        self._name = val

    def readable_history(self, client):
        message_history = ['{}: {}'.format(message.author.chat_name, message.text) for message in self.messages if not message.targets or client in message.targets] # BUG currently on reconnection user wont get messages that were targeted at him during previous session
        return '\n'.join(message_history)

    def is_command(self, message):
        return message.text.startswith('::') 

    def get_client(self, websocket):
        for client in self.clients.copy():
            if client.websocket == websocket:
                return client
        return False

    def preprocess_command(self, message):
        client = message.author
        text = message.text[2:]
        command_components = text.split(' ')
        command = command_components[0]
        args = command_components[1:]
        return command, args

    def valid_room_name(self, text):
        if not text.strip():
            return False
        return True

    async def on_client_joined(self, client):
        logger.debug('Client joined room {} {} : {}'.format(self.room_type, self._name, client.username))
        await self.send_system_message(SystemMessage(self, 'joined_room',[self.uid, self.name, self.room_type], targets=[client]))
        history = self.readable_history(client)
        if history:
            logger.debug('{} {} : Sending room history to client {}'.format(self.room_type, self._name, client))
            await self.send_text(history, [client])
       # message = Message(self, '{} connected'.format(client.username))
        logger.debug('{} {} : Sending client_joined_room sysmsg {}'.format(self.room_type, self._name, client))
        await self.send_system_message(SystemMessage(self, 'client_joined_room',[client.uid, client.username]))
        #await self.send_message(message)

    async def on_client_disconnected(self, client):
        #message = Message(self, '{} disconnected'.format(client.username))
        #await self.send_message(message)   
        logger.debug('{} {} : Sending client_left_room sysmsg {}'.format(self.room_type, self._name, client))
        await self.send_system_message(SystemMessage(self, 'client_left_room',[client.uid, client.username]))

    async def handle_command(self, message):
        logger.debug('{} {} : handling command by client {}: {}'.format(self.room_type, self._name, message.author, message.text))

    async def handle_message(self, client, text):
        logger.debug('{} {} : handling message by client {}: {}'.format(self.room_type, self._name, client, text))
        if not text.strip():
            return None
        message = Message(client, text.strip())
        if not self.get_client(client.websocket):
            raise(ClientNotRegisteredInRoomException())

        if self.is_command(message):

            await self.handle_command(message)
        else:
            await self.send_message(message)

    async def register_client(self, client):
        try:
            logger.debug('{} {} : registering client {}'.format(self.room_type, self._name, client))
            self.clients.add(client)
            client.room = self
            await self.on_client_joined(client)
            return client
        except ClientAlreadyExistsException as e:
            await self.server.send('Client already registered', client.websocket)


    async def remove_client(self, client):
        logger.debug('{} {} : removing client {}'.format(self.room_type, self._name, client))
        for c in self.clients.copy():
            if c.websocket == client.websocket:
                self.clients.remove(client)
                await self.on_client_disconnected(client)
                break

    async def send_text(self, text, targets): #Sending text doesn't show an author and is never logged
        logger.debug('{} {} : sending raw text {}, {}'.format(self.room_type, self._name, text, str(targets)))
        if not targets:
            targets = self.clients
        sending_list = [self.server.send("{}".format(text), client.websocket) for client in targets]
        if sending_list:
            done, pending = await asyncio.wait(sending_list)

    async def send_message(self, message, log = True, no_author = False):
        
        targets = message.targets
        author = message.author
        text = message.text

        logger.debug('{} {} : sending chat message, author:{}, targets:{}, text:{}'.format(self.room_type, self._name, author, str(targets), text))

        if not targets:
            targets = self.clients #If no target is set its a global (room) message
        if not no_author:
            sending_list = [self.server.send("{}: {}".format(author.chat_name, text), client.websocket) for client in targets]
        else:
            sending_list = [self.server.send("{}".format(text), client.websocket) for client in targets]
        if sending_list:
            done, pending = await asyncio.wait(sending_list)
        if log:
            self.messages.append(message)

    async def send_system_message(self, msg):
        targets = msg.targets
        logger.debug('{} {} : sending system message, emitter:{}, msg_type:{}, targets:{}, args:{}'.format(self.room_type, self._name, msg.emitter,msg.msg_type, str(msg.targets), str(msg.args)))
        if not targets:
            targets = self.clients #If no target is set its a global (room) message
        sending_list = [self.server.send("sysmsg|{}|{}|{}".format(msg.emitter.uid, msg.msg_type, '|'.join([str(x) for x in msg.args])), client.websocket) for client in targets]
        if sending_list:
            done, pending = await asyncio.wait(sending_list)

    def __repr__(self):
        return 'room|'+self.uid+'|'+self.room_type+'|'+self._name


    
class SubRoom(Room):
    async def remove_client(self, client):
        await super(SubRoom, self).remove_client(client)
        if not self.clients: # Suicide
            logger.debug('{} {} : destroying room.'.format(self.room_type, self._name))
            self.server.rooms.remove(self)
            self = None


class SkeletonRoom(SubRoom):
    chat_name = "Spooky voice"
    room_type = 'skeleton'
    def __init__(self, server=None, loop=None, messages = None, clients = None, uid = None, _name = None, skeleton=None, players=None):
        super(SkeletonRoom, self).__init__(server, loop, messages, clients, uid, _name)


        self.skeleton = skeleton or skeletons.Skeleton(loop = self.loop,name='skeleton')
        if not self._name:
            self._name = 'Skeleton fight'
        self.skeleton.emit_message = self.handle_game_message
        self.players = players or []

        logger.debug('{} {} : starting skeleton'.format(self.room_type, self._name))
        self.start_game()

    async def remove_client(self, client):
        await super(SkeletonRoom, self).remove_client(client)
        if self and (not self.clients or not [client for client in self.clients if client.player.alive]):
            if self in self.server.rooms:
                logger.debug('{} {} : destroying skeleton room.'.format(self.room_type, self._name))
                self.server.rooms.remove(self)  # Suicide
            self = None

    def handle_game_message(self, emitter, msg_type, *args):
        logger.debug('{} {} : handling game message, emitter:{}, msg_type:{}, args:{}.'.format(self.room_type, self._name, emitter, msg_type, str(args)))
        if not msg_type in GameSystemMessage.valid_msg_types:
            logger.error("Invalid sys message received from game.")

        if msg_type == 'ply_notify':
            player = emitter
            client = None
            for cl in self.clients:
                if cl.player == player:
                    client = cl
                    break
            if client:
                message = Message(self, ' '.join([str(x) for x in args]), targets=[client])
                self.loop.create_task(self.send_message(message, no_author=True))
                return 

        if msg_type == 'ai_new_target':
            target = args[0]
            args = [target.uid]

        #Send the message for the client to handle
        sys_message = SystemMessage(emitter, msg_type, list(args))
        self.loop.create_task(self.send_system_message(sys_message))


    async def on_client_joined(self, client):
        logger.debug('Client joined room {} {} : {}'.format(self.room_type, self._name, client.username))
        await self.send_system_message(SystemMessage(self, 'joined_room',[self.uid, self.name, self.room_type], targets=[client]))
        ply = skeletons.Player(uid=client.uid, loop = self.loop,name=client.username, target=self.skeleton, client=client)
        ply.target = self.skeleton
        ply.emit_message = self.handle_game_message
        client.player = ply
        self.skeleton.targets.append(client.player)
        logger.debug('{} {} : Sending client_joined_room sysmsg {}'.format(self.room_type, self._name, client))
        await self.send_system_message(SystemMessage(self, 'client_joined_room',[client.uid, client.username]))

        logger.debug('{} {} : Sending ui_setup_creature skeleton sysmsgs'.format(self.room_type, self._name))
        ui_setup_msg = GameSystemMessage(self, 'ui_setup_creature', self.skeleton.full_report(), [client])
        await self.send_system_message(ui_setup_msg)


        for cl in self.clients:
            ui_setup_msg = GameSystemMessage(self, 'ui_setup_creature', cl.player.full_report())
            logger.debug('{} {} : Sending ui_setup_creature player sysmsg {}'.format(self.room_type, self._name, client))
            await self.send_system_message(ui_setup_msg)


        #message = Message(self, '{} entered the skeleton fight!'.format(client.username))
        #await self.send_message(message)



        
    async def on_client_disconnected(self, client):
        await super(SkeletonRoom, self).on_client_disconnected(client)
        self.skeleton.targets.remove(client.player)
        if self.skeleton.target == client.player:
            self.skeleton.target = None
        client.player = None
        #message = Message(self, '{} ran from the fight!'.format(client.username))
        #await self.send_message(message)


    def start_game(self):
        logger.debug('{} {} : starting skeleton AI'.format(self.room_type, self._name))
        ai_task = asyncio.ensure_future(self.skeleton.run())
        #player_task = asyncio.ensure_future(self.player.run())

    async def handle_command(self, message):
        await super(SkeletonRoom, self).handle_command(message)
        client = message.author
        text = message.text
        command, args = self.preprocess_command(message)
        logger.debug('{} {} : handling command  author:{}, text:{}, command:{}, args:{}'.format(self.room_type, self._name, client, text, command, args))
        async def handle_attack(*args):
            max_args_len = 0
            if len(args) > max_args_len:
                return "Too many arguments, expected {}".format(max_args_len)

            await client.player.attack()
            return 0

        async def handle_defense(*args):
            max_args_len = 0
            if len(args) > max_args_len:
                return "Too many arguments, expected {}".format(max_args_len)

            await client.player.defend()
            return 0

        async def handle_leave(*args):
            max_args_len = 0
            if len(args) > max_args_len:
                return "Too many arguments, expected {}".format(max_args_len)

            await client.room.remove_client(client)
            await self.server.room.register_client(client) #back to lobby
            return 0


        available_commands = {
            "leave":handle_leave,
            'attack':handle_attack,
            "defense":handle_defense
        }
        error_text = None
        
        if command in available_commands.keys():
            result = await available_commands[command](*args)
            if result:
                error_text = '{}'.format(result)
        else:
            error_text =  'Unrecognized command.'

        if error_text:
            error_message = SystemMessage(emitter=self, msg_type='validation_error', args=[error_text], targets=[client])
            await self.send_system_message(error_message)




class ChatRoom(SubRoom):
    chat_name = 'Chat'
    room_type = 'chat'
    async def handle_command(self, message):
        client = message.author
        text = message.text
        command, args = self.preprocess_command(message)

        async def handle_leave(*args):
            max_args_len = 0
            if len(args) > max_args_len:
                return "Too many arguments, expected {}".format(max_args_len)

            await client.room.remove_client(client)
            await self.server.room.register_client(client) #back to lobby
            return 0

        available_commands = {
            "leave":handle_leave,
        }

        error_text = None
        
        if command in available_commands.keys():
            result = await available_commands[command](*args)
            if result:
                error_text = '{}'.format(result)
        else:
            error_text =  'Unrecognized command.'

        if error_text:
            error_message = SystemMessage(emitter=self, msg_type='validation_error', args=[error_text], targets=[client])
            await self.send_system_message(error_message)



class LobbyRoom(Room):
    chat_name = 'Lobby'
    room_type = 'lobby'
    async def register_client(self, client):
        try:
            logger.debug('{} {} : registering client {}'.format(self.room_type, self._name, client))
            self.clients.add(client)
            client.room = self
            await self.send_system_message(SystemMessage(self, 'registered',[client.uid, client.username], targets=[client]))
            await self.on_client_joined(client)
            logger.info('{} {} : registered client {}'.format(self.room_type, self._name, client))
            return client
        except ClientAlreadyExistsException as e:
            await self.server.send('Client already registered', client.websocket)

    async def handle_command(self, message):
        await super(LobbyRoom, self).handle_command(message)
        client = message.author
        text = message.text
        command, args = self.preprocess_command(message)

        logger.debug('{} {} : handling command  author:{}, text:{}, command:{}, args:{}'.format(self.room_type, self._name, client, text, command, args))

        async def handle_join(*args):
            max_args_len = 1
            if len(args) > max_args_len:
                return "Too many arguments, expected {}".format(max_args_len)
            room_name = args[0]

            new_room = None
            for room in self.server.rooms:
                if room.name == room_name:
                    new_room = room
                    break

            if not new_room:
                return "There is no room with name {}.".format(room_name)

            await client.room.remove_client(client)
            await new_room.register_client(client)

            return 0 
            


        async def handle_create(*args):
            min_args_len = 1
            max_args_len = 1
            if len(args) > max_args_len:
                return "Too many arguments, expected at most {}.".format(max_args_len)
            if len(args) < min_args_len:
                return "Too few arguments, expected at least {}.".format(min_args_len)
            room_name = args[0]

            for room in self.server.rooms:
                if room.name == room_name:
                    return "Room name {} is taken, choose another.".format(room_name)

            new_room = ChatRoom(self.server, self.loop, _name=room_name)
            
            await client.room.remove_client(client)
            await new_room.register_client(client)
            self.server.rooms.append(new_room)
            return 0

        async def handle_skeleton(*args):
            min_args_len = 0
            max_args_len = 1
            if len(args) > max_args_len or len(args) < min_args_len:
                return "Skeleton name should be a single word."

            if len(args) > 0:
                room_name = args[0]
            else:
                room_name = random.choice([name for name in skeletons.Skeleton.skeleton_names if not name in [room.name for room in self.server.rooms]])
            if not self.valid_room_name(room_name):
                return "Invalid name"

            new_room = None
            for room in self.server.rooms:
                if room.name == room_name:
                    new_room = room
                    if len(new_room.clients) > 1:
                        return "That skeleton fight already has 2 warriors, you can't join."

            if not new_room:
                new_room = SkeletonRoom(self.server, self.loop, _name = room_name)
            
            await client.room.remove_client(client)
            await new_room.register_client(client)
            self.server.rooms.append(new_room)
            return 0

        
        available_commands = {
            #"join":handle_join,
            #"create":handle_create,
            "skeleton":handle_skeleton,
        }
        error_text = None
        
        if command in available_commands.keys():
            result = await available_commands[command](*args)
            if result:
                error_text = '{}'.format(result)
        else:
            error_text =  'Unrecognized command.'

        if error_text:
            error_message = SystemMessage(emitter=self, msg_type='validation_error', args=[error_text], targets=[client])
            await self.send_system_message(error_message)

class ChatServer:
    def __init__(self, host=HOST, port=PORT, loop=None, messages = None, clients = None, rooms = None, skeletons = None):
        self.host = host
        self.port = port
        self.loop = loop or asyncio.get_event_loop()
        self.room = LobbyRoom(self, loop, messages, clients, _name='lobby room')
        self.rooms = rooms or []

    def __str__(self):
        return "ChatServer"

    def get_client(self, websocket):
        client = self.room.get_client(websocket)
        if not client:
            for room in self.rooms:
                client = room.get_client(websocket)
                if client:
                    return client
        else:
            return client
        return None

    async def send(self, text, websocket):
        logger.debug('Server sending: {}'.format(text))
        await websocket.send(text)

    def valid_username(self, text):
        if not text.strip() or ':' in text:
            return False

        for client in self.room.clients:
            if client.username == text:
                return False
        for room in self.rooms:
            for client in room.clients:
                if client.username == text:
                    return False
        return True

    async def handler(self, websocket, path):
        client = None
        while True:
            try:
                client = self.get_client(websocket)
                if not client:
                    logger.info("Unregistered client connection")
                    client = Client(websocket=websocket)
                    logger.debug("Prompting for username")
                    await websocket.send('sysmsg||username_prompt')
                    username = await websocket.recv()
                    
                    if not self.valid_username(username):
                        logger.debug("Received invalid username: {}".format(username))
                        await websocket.send('sysmsg||username_invalid')
                        continue
                    logger.debug("Received valid username: {}".format(username))
                    client.username = username
                    await self.room.register_client(client)
                    
                text = await websocket.recv()
                logger.debug(' '.join(['Received from ',client.username,':', text]))
                response = await client.room.handle_message(client, text)

            except websockets.exceptions.ConnectionClosed as e:
                if client and client.room:
                    await client.room.remove_client(client)                    
                break

    def run(self):
        logger.info('Starting server')
        self.websocket_server = websockets.serve(self.handler, self.host, self.port, timeout=60)
        self.loop.run_until_complete(self.websocket_server)
        asyncio.async(wakeup()) #HACK so keyboard interrupt works on Windows
        self.loop.run_forever()
        self.loop.close()
        self.clean_up()

    def clean_up(self):
        logger.info('Cleaning up ')
        self.websocket_server.close()
        for task in asyncio.Task.all_tasks():
            task.cancel()


async def wakeup(): # HACK  http://stackoverflow.com/questions/27480967/why-does-the-asyncios-event-loop-suppress-the-keyboardinterrupt-on-windows
    while True:
        await asyncio.sleep(1) 

if __name__ == '__main__':
    args = sys.argv[1:]
    if len(args) > 0:
        PORT = args[0]

    loop = asyncio.get_event_loop()
    chat = ChatServer(loop=loop, port=PORT, host=HOST)
    chat.run()
