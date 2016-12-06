import asyncio
import websockets
import uuid
import signal
import functools 
import skeletons
import concurrent
HOST ='localhost'
PORT = 8765

#todo 
# 0. 
# 1. Add skeletons

class ClientAlreadyExistsException(Exception):
    pass

class ClientNotRegisteredInRoomException(Exception):
    pass

class SystemMessage():
    valid_msg_types = [
        'registered', #client.uid, client.username
        'joined_room', #room.uid, room.name
        'client_joined_room', #client.uid, client.username
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


class Room():
    chat_name = 'GLOBAL'
    room_actions = []
    def __init__(self, server=None, loop=None, messages = None, clients = None, uid = None, _name = None):
        self.server = server
        self.loop = loop or asyncio.get_event_loop()
        self.messages = messages or []
        self.clients = clients or set()
        self.uid = uid or str(uuid.uuid4())[:8]
        self._name = _name or None

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

    async def on_client_joined(self, client):
        await self.send_system_message(SystemMessage(self, 'joined_room',[self.uid, self.name], targets=[client]))
        history = self.readable_history(client)
        if history:
            await self.send_text(history, [client])
        message = Message(self, '{} connected'.format(client.username))
        await self.send_system_message(SystemMessage(self, 'client_joined_room',[client.uid, client.username]))
        await self.send_message(message)

    async def on_client_disconnected(self, client):
        message = Message(self, '{} disconnected'.format(client.username))
        await self.send_message(message)

    async def handle_command(self, message):
        pass

    async def handle_message(self, client, text):
        message = Message(client, text.strip())
        if not self.get_client(client.websocket):
            raise(ClientNotRegisteredInRoomException())

        if self.is_command(message):
            await self.handle_command(message)
        else:
            await self.send_message(message)

    async def register_client(self, client):
        try:
            self.clients.add(client)
            client.room = self
            await self.on_client_joined(client)
            return client
        except ClientAlreadyExistsException as e:
            await self.server.send('Client already registered', client.websocket)


    async def remove_client(self, client):
        for c in self.clients.copy():
            if c.websocket == client.websocket:
                self.clients.remove(client)
                await self.on_client_disconnected(client)
                break

    async def send_text(self, text, targets): #Sending text doesn't show an author and is never logged
        if not targets:
            targets = self.clients
        sending_list = [self.server.send("{}".format(text), client.websocket) for client in targets]
        if sending_list:
            done, pending = await asyncio.wait(sending_list)

    async def send_message(self, message, log = True, no_author = False):
        targets = message.targets
        author = message.author
        text = message.text
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
        if not targets:
            targets = self.clients #If no target is set its a global (room) message
        sending_list = [self.server.send("sysmsg|{}|{}|{}".format(msg.emitter.uid, msg.msg_type, '|'.join([str(x) for x in msg.args])), client.websocket) for client in targets]
        if sending_list:
            done, pending = await asyncio.wait(sending_list)

    
class SubRoom(Room):
    async def remove_client(self, client):
        await super().remove_client(client)
        if not self.clients: # Suicide
            self.server.rooms.remove(self)
            self = None


class SkeletonRoom(SubRoom):
    chat_name = "Spooky voice"
    def __init__(self, server=None, loop=None, messages = None, clients = None, uid = None, _name = None, skeleton=None, players=None):
        super(SkeletonRoom, self).__init__(server, loop, messages, clients, uid, _name)


        self.skeleton = skeleton or skeletons.Skeleton(loop = self.loop,name='skeleton')
        self.skeleton.emit_message = self.handle_game_message
        self.players = players or []

        self.start_game()

    async def remove_client(self, client):
        await super().remove_client(client)
        if not self.clients or not [client for client in self.clients if client.player.alive]: # Suicide
            self.server.rooms.remove(self)
            self = None

    def handle_game_message(self, emitter, msg_type, *args):
        if not msg_type in GameSystemMessage.valid_msg_types:
            raise(Exception("Invalid message received from game."))

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
            args = [target.name]

        #Send the message for the client to handle
        sys_message = SystemMessage(emitter, msg_type, list(args))
        self.loop.create_task(self.send_system_message(sys_message))


    async def on_client_joined(self, client):
        ply = skeletons.Player(loop = self.loop,name=client.username, target=self.skeleton, client=client)

        ply.target = self.skeleton
        ply.emit_message = self.handle_game_message
        client.player = ply
        self.skeleton.targets.append(client.player)

        ui_setup_msg = GameSystemMessage(self, 'ui_setup_creature', self.skeleton.full_report(), [client])
        await self.send_system_message(ui_setup_msg)

        for cl in self.clients:
            ui_setup_msg = GameSystemMessage(self, 'ui_setup_creature', cl.player.full_report(), [client])
            await self.send_system_message(ui_setup_msg)

        message = Message(self, '{} entered the skeleton fight!'.format(client.username))
        await self.send_message(message)



        
    async def on_client_disconnected(self, client):
        self.skeleton.targets.remove(client.player)
        if self.skeleton.target == client.player:
            self.skeleton.target = None
        client.player = None
        message = Message(self, '{} ran from the fight!'.format(client.username))
        await self.send_message(message)


    def start_game(self):
        ai_task = asyncio.ensure_future(self.skeleton.run())
        #player_task = asyncio.ensure_future(self.player.run())

    async def handle_command(self, message):
        client = message.author
        text = message.text
        command, args = self.preprocess_command(message)

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

        error_message = Message(author=self, targets=[client])
        if command in available_commands.keys():
            result = await available_commands[command](*args)
            if result:
                error_message.text = 'Error: {}'.format(result)
        else:
            error_message.text =  'Unrecognized command'

        if error_message.text:
            await self.send_message(error_message, log = False)




class ChatRoom(SubRoom):
    chat_name = 'Chat'

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

        error_message = Message(author=self, targets=[client])
        if command in available_commands.keys():
            result = await available_commands[command](*args)
            if result:
                error_message.text = 'Error: {}'.format(result)
        else:
            error_message.text =  'Unrecognized command'

        if error_message.text:
            await self.send_message(error_message, log = False)



class LobbyRoom(Room):
    chat_name = 'Lobby'
    async def register_client(self, client):
        try:
            self.clients.add(client)
            client.room = self
            await self.send_system_message(SystemMessage(self, 'registered',[client.uid, client.username], targets=[client]))
            await self.on_client_joined(client)
            return client
        except ClientAlreadyExistsException as e:
            await self.server.send('Client already registered', client.websocket)

    async def handle_command(self, message):
        client = message.author
        text = message.text
        command, args = self.preprocess_command(message)
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
                return "Too many arguments, expected at most{}.".format(max_args_len)
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
            min_args_len = 1
            max_args_len = 1
            if len(args) > max_args_len:
                return "Too many arguments, expected at most{}.".format(max_args_len)
            if len(args) < min_args_len:
                return "Too few arguments, expected at least {}.".format(min_args_len)
            room_name = args[0]

            new_room = None
            for room in self.server.rooms:
                if room.name == room_name:
                    new_room = room

            if not new_room:
                new_room = SkeletonRoom(self.server, self.loop, _name=room_name)
            
            await client.room.remove_client(client)
            await new_room.register_client(client)
            self.server.rooms.append(new_room)
            return 0

        
        available_commands = {
            "join":handle_join,
            "create":handle_create,
            "skeleton":handle_skeleton,
        }

        error_message = Message(author=self, targets=[client])
        if command in available_commands.keys():
            result = await available_commands[command](*args)
            if result:
                error_message.text = 'Error: {}'.format(result)
        else:
            error_message.text =  'Unrecognized command'

        if error_message.text:
            await self.send_message(error_message, log = False)

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
        print('>', text)
        await websocket.send(text)

    def valid_username(self, text):
        if text.strip() and not ':' in text:
            return True
        return False

    async def handler(self, websocket, path):
        client = None
        while True:
            try:
                client = self.get_client(websocket)
                if not client:
                    client = Client(websocket=websocket)
                    await websocket.send('Please register by typing your username')
                    username = await websocket.recv()
                    if not self.valid_username(username):
                        await websocket.send('Invalid username, try another')
                        continue
                    client.username = username
                    await self.room.register_client(client)
                    
                text = await websocket.recv()
                print('<', text)
                response = await client.room.handle_message(client, text)

            except websockets.exceptions.ConnectionClosed as e:
                if client and client.room:
                    await client.room.remove_client(client)                    
                break

    def run(self):
        self.websocket_server = websockets.serve(self.handler, self.host, self.port, timeout=60)
        self.loop.run_until_complete(self.websocket_server)
        asyncio.async(wakeup()) #HACK so keyboard interrupt works on Windows
        self.loop.run_forever()
        self.loop.close()
        self.clean_up()

    def clean_up(self):
        self.websocket_server.close()
        for task in asyncio.Task.all_tasks():
            task.cancel()


async def wakeup(): # HACK  http://stackoverflow.com/questions/27480967/why-does-the-asyncios-event-loop-suppress-the-keyboardinterrupt-on-windows

    while True:
        await asyncio.sleep(1) 

if __name__ == '__main__':
    loop = asyncio.get_event_loop()
    chat = ChatServer(loop=loop)


    chat.run()
