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

class Message():
    def __init__(self, author = None, text = None, targets = None):
        self.author = author 
        self.text = text
        self.targets = targets

class Client():
    def __init__(self, websocket=None,username=None, room=None, player=None):
        self.websocket = websocket
        self.username = username
        self.room = room
        self.player = player

    @property
    def chat_name(self):
        return self.username


class Room():
    chat_name = 'GLOBAL'

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
        message = Message(self, "Welcome to the {}! Here's what happened before you came:".format(self.name))
        await self.send_message(message, log=False)
        history = self.readable_history(client)
        if history:
            await self.send_text(history, [client])
        message = Message(self, '{} connected'.format(client.username))
        await self.send_message(message)

    async def on_client_disconnected(self, client):
        message = Message(self, '{} disconnected'.format(client.username))
        await self.send_message(message)

    async def handle_command(self, message):
        #message = Message(self, 'Unrecognized command', targets=[client])
        #await self.send_message(message, log = False) 
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

        def emit_message(creature, text):
            if isinstance(creature, skeletons.Player):
                clients = [client for client in self.clients if client.player == creature]
                if clients:
                    client = clients[0]
                else:
                    return False
                message = Message(client, text)
            else:
                message = Message(self, text)

            self.loop.create_task(self.send_message(message, no_author=True))

        self.emit_message = emit_message

        self.skeleton = skeleton or skeletons.Skeleton(loop = self.loop,name='skeleton')
        self.skeleton.emit_message = emit_message
        self.players = players or []

        self.start_game()

    async def on_client_joined(self, client):
        ply = skeletons.Player(loop = self.loop,name=client.username, target=self.skeleton, client=client)

        ply.target = self.skeleton
        ply.emit_message = self.emit_message
        client.player = ply
        self.skeleton.targets.append(client.player)
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
                response = await client.room.handle_message(client, text)

            except websockets.exceptions.ConnectionClosed as e:
                if client and client.room:
                    await client.room.remove_client(client)                    
                break

    def run(self):
        self.websocket_server = websockets.serve(self.handler, self.host, self.port)
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
