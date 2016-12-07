from transitions import Machine
import asyncio
import random
import concurrent
import uuid

class Creature:
    states = ['idle', 'attacking', 'defending', 'dead']
    def __init__(self, name, uid=None, alive=True, machine=None, max_health=100, damage=5, action_time=3, target=None):
        self.uid = uid or str(uuid.uuid4())[:8]
        self.name = name
        self.alive = alive
        self.max_health = max_health
        self.health = 100
        self.defense = False
        self.target = target
        self.damage = damage

        self.action_time = action_time

        self.action_task = None

        self.machine = machine or Machine(model=self, states=Creature.states, initial='idle', after_state_change='alert_state_change')
        self.machine.add_transition(trigger='begin_attack', source='idle', dest='attacking', after = 'on_begin_attack')
        self.machine.add_transition(trigger='interrupt', source='attacking', dest='idle', after = 'on_interrupt')
        self.machine.add_transition(trigger='begin_defense', source='idle', dest='defending', after = 'on_defend')
        self.machine.add_transition(trigger='action_complete', source='attacking', dest='idle', after='on_attack')
        self.machine.add_transition(trigger='action_complete', source='defending', dest='idle', after='stop_defense')

        for state in Creature.states:
            if state != 'dead':
                self.machine.add_transition(trigger='die', source=state, dest='dead', after='on_death')

    def full_report(self):
        rep = [str(x) for x in [self.uid, self.name, self.alive, self.max_health, self.health, self.state]]
        if self.target:
            rep.append(str(self.target.name))
        return rep

    def emit_message(self, emitter, msg_type, *args):
        print(args)

    def check_alive(self):
        if self.health <= 0:
            self.alive = False
            self.die()

    def take_damage(self, dmg):
        if not self.defense:
            if self.state == 'attacking':
                self.interrupt()
            self.emit_message(self,"creature_took_damage", dmg)
            self.health = self.health - dmg
            self.emit_message(self,"creature_health_report", self.health)
            self.check_alive()
        else:
            self.emit_message(self,"creature_blocked_damage")

    def alert_state_change(self):
        self.emit_message(self,"creature_changed_state", self.state)

    def ambient_sounds(self):
        general_text = []
        if self.health < 50:
            health_text = ["Creature has not much hp"]
        elif self.health < 25:
            health_text = ["Creature almost dead"]
        else:
            health_text = ["Creature looks pretty healthy"]

        sound= random.choice(general_text + health_text)

    def on_death(self):
        self.emit_message(self, "creature_death")

    def on_interrupt(self):
        self.action_task.cancel()
        self.action_task = None
        self.emit_message(self, "creature_action_interrupted")

    def on_begin_attack(self):
        self.emit_message(self, "creature_attack_started")

    def on_attack(self):
        self.emit_message(self, "creature_attack_finished")
        if self.target:
            self.target.take_damage(self.damage)

    def on_defend(self):
        self.emit_message(self, "creature_def")
        self.defense = True

    def stop_defense(self):
        self.emit_message(self, "creature_no_def")
        self.defense = False

    async def run(self):
        self.emit_message(self, 'creature_start')

    

class Skeleton(Creature):

    skeleton_names = [
        "Abanquetan","Chafret","Frastin","Lebald","Roset",
    "Adalbain","Chanis","Frith","Leofmar","Rummoth",
    "Adene","Chard","Fritiltel","Leona","Runadon",
    "Ading","Christala","Frond","Lethe","Ruppo",
    "Aebbie","Chrithep","Gabilinn","Liutperi","Sabariver",
    "Alter","Coros","Gisela","Maladias","Savens",
    "Amallovan","Coudagi","Gleid","Maldui","Sconius",
    "Amanui","Crist","Gliforoth","Mallocke","Scropa",
    "Amatt","Cropre","Glowin","Malloria","Serick",
    "Amring","Cruel","Goibhach","Malys","Sevanion",
    "Anberg","Cuilo","Goonen","Mardun","Shani",
    "Araldor","Darresa","Gunnath","Megin","Sperhaell",
    "Arbelath","Daurenna","Gwathain","Meldir","Spesi",
    "Argad","Davina","Gwenie","Melrett","Sreoter",
    "Arias","Deadan","Gwenvel","Melve","Starollian",
    "Artus","Delmordian","Herbod","Milimedoc","Surryngel",
    "Arvedane","Derret","Heriulf","Miodowieft","Sveige",
    "Athan","Destica","Hharr","Moray","Sylte",
    "Atten","Devyn","Hildere","Morgan","Taeret",
    "Bighredigh","Ebervara","Iavalis","Nguan","Tharkathel",
    "Bioregnir","Echilda","Iboiselvar","Nimbas","Thearc",
    "Bitireana","Edrovan","Ilmar","Nimrasa","Think",
    "Bjorn","Edwulf","Imann","Nimrodric","Thomar",
    "Blaimich","Edyon","Immona","Nitiuba","Thron",
    "Bouda","Elgil","Irvyn","Opathy","Tibold",
    "Brach","Eliadafi","Iseach","Orgetesset","Tince",
    "Bradwaith","Elnothath","Isoreth","Orgettanya","Tiscis",
    "Braignus","Elshane","Issiror","Osgilos","Tofithlain",
    "Brigan","Erist","Josciot","Pedra","Tynawd",
    "Brindes","Ernoran","Josine","Pegan","Tyrkade",
    "Brith","Esunius","Jozennain","Pehryth","Ulfus",
    "Brithecra","Etachibeth","Juice","Pelice","Untig",
    "Brithnico","Ethian","Kaila","Perdus","Uratham",
    "Budon","Falorix","Kelsigur","Poilton","Vitus",
    "Buros","Farlindon","Kenedil","Possipsi","Voriz",
    "Caira","Farnouga","Kenez","Prabanaera","Waingold",
    "Camrin","Felle","Kennyn","Praso","Wallyn",
    "Caratus","Fertan","Kenulf","Prettanon","Weret",
    "Carden","Feyne","Keriath","Quodhach","Wernin",
    "Cartildath","Finive","Kiricuros","Regovan","Womanor",
    "Cealda","Florier","Kristhilda","Riciot","Yashadrus",
    "Cealti","Foiliann","Kylin","Riomareki","Ysmenefer",
    "Celota","Fraer","Launde","Rohelwynne","Zenwy",
    "Cemettig","Frames","Leasach","Rohild","Zoranz",

    ]
    def __init__(self, name, uid = None, loop = None, alive=True, machine=None, max_health=100,  damage=5,action_time=3, target=None, targets=None):
        super(Skeleton, self).__init__(name, uid, alive, machine, max_health, damage,action_time, target)
        self.loop = loop or asyncio.get_event_loop()
        self.targets = targets or []

    async def run(self):
        await super(Skeleton, self).run()
        while True:
            if self.alive:
                if not self.target or not self.target.alive:
                    if len([x for x in self.targets if x.alive]) == 0:
                        await asyncio.sleep(5)
                    else:
                        self.target = random.choice(self.targets)
                        #self.emit_message(self, 'Skeleton picked a new target: {}'.format(self.target.name))
                        self.emit_message(self,"ai_new_target", self.target)

                if self.target and self.target.alive:
                    if self.state == 'idle':
                        dice_roll = random.choice([1, 2])
                        if dice_roll == 1:
                            #defend
                            self.begin_defense()
                            self.action_task = self.loop.call_later(self.action_time, self.action_complete)
                        elif dice_roll:
                            #attack
                            self.begin_attack()
                            self.action_task = self.loop.call_later(self.action_time, self.action_complete)  
            else:
                break

            await asyncio.sleep(1)

class Player(Creature):
    def __init__(self, name, uid=None, loop = None, alive=True, machine=None, max_health=100, damage=20, action_time=2, target=None, client=None):
        super(Player, self).__init__(name, uid, alive, machine, max_health, damage, action_time, target)
        self.loop = loop or asyncio.get_event_loop()
        self.client = client

    async def attack(self):
        if self.alive and self.target and self.target.alive:
            if self.state == 'idle':
                    self.begin_attack()
                    self.action_task = self.loop.call_later(self.action_time, self.action_complete)    
            else:
                self.emit_message(self,"ply_notify", "Can't attack now!")

    async def defend(self):
        if self.alive and self.target and self.target.alive:
            if self.state == 'idle':
                    self.begin_defense()
                    self.action_task = self.loop.call_later(self.action_time, self.action_complete)
            else:
                self.emit_message(self,"ply_notify", "Can't defend now!")      

