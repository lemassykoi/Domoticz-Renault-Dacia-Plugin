#!/usr/bin/python3
# -*- coding: utf-8 -*-
#
# Renault/Dacia domoticz plugin
# Based on Hyundai Kia plugin plugin by CreasolTech
# Based on renault-api plugin by hacf-fr
#
# Source:  TODO
# Author:  Richeux
# License: MIT


"""
<plugin key="domoticz-renault-dacia" name="Renault / Dacia connect" author="Richeux" version="1.1.0" wikilink="https://github.com/lemassykoi/Domoticz-Renault-Dacia-Plugin" externallink="https://renault-api.readthedocs.io/en/latest/index.html">
    <description>
        <h2>Domoticz Renault / Dacia plugin</h2>
        This plugin permits to access, through the Renault/Dacia account credentials, to information about owned electric vehicles<br/>
    </description>
    <params>
        <param field="Username" label="Email address" width="300px" required="true" />
        <param field="Password" label="Password" width="300px" required="true" password="true" />
        <param field="Mode1" label="Accound id" width="300px" />
        <param field="Mode2" label="VIN" width="300px" />
        <param field="Mode3" label="Capacité utile de la batterie (kWh)" width="300px" default="26.8">
        <description>La capacité de la batterie est requise pour estimer les temps de chargement lors de la programmation. Nombre décimal séparé par un point.</description>
        </param>
        <param field="Mode4" label="Fréquence d'actualisation" width="300px">
            <options>
                <option label="5 minutes" value="5"/>
                <option label="10 minutes" value="10"/>
                <option label="15 minutes" value="15"/>
                <option label="20 minutes" value="20"/>
                <option label="30 minutes" value="30" default="true" />
                <option label="1 heure" value="60"/>
                <option label="6 heures" value="360"/>
                <option label="12 heures" value="720"/>
                <option label="24 heures" value="1440"/>
            </options>
        </param>
        <param field="Mode5" label="Services actifs" width="300px">
            <options>
                <option label="Cockpit + Batterie + Localisation" value="111" default="true" />
                <option label="Cockpit" value="100"/>
                <option label="Cockpit + Batterie" value="110"/>
                <option label="Cockpit + Localisation" value="101"/>
                <option label="Batterie" value="010"/>
                <option label="Batterie + Localisation" value="011"/>
                <option label="Localisation" value="001"/>
                <option label="Aucun" value="0"/>
            </options>
        </param>
        <param field="Mode6" label="IDX capteur puissance Shelly (détection arrêt R5, ex: 29)" width="100px" />
        <param field="Address" label="IDX relais/interrupteur Shelly (coupe le courant, ex: 28)" width="100px" />
    </params>
</plugin>
"""

import Domoticz as Domoticz
import aiohttp
import asyncio
import json
from datetime import datetime
from renault_api.renault_client import RenaultClient
from renault_api.renault_account import RenaultAccount
from renault_api.renault_account import RenaultVehicle
from renault_api.kamereon import models
from renault_api.exceptions import EndpointNotAvailableError
from shutil import copy2
import os

class BasePlugin:
    enabled = False
    def __init__(self):
        self._updateInterval = 30       # update interval in minutes (must be >=5 ; l'API Kamereon plafonne ~60 requêtes/heure)
        self._lastUpdate = None         # last time the server has been requested
        self._vehicle = None            # last vehicle data
        self._Battery = None            # last vehicle data
        self._Cockpit = None            # last vehicle data
        self._Location = None           # last vehicle data
        self._domoticzPort = None       # port de l'API web Domoticz (auto-détecté)
        return
        
    def onHeartbeat(self):
        self._updateInterval = int(Parameters["Mode4"])
        loop = asyncio.get_event_loop() 
        if self.mustUpdate():
            self._lastUpdate = datetime.now()
            if Parameters["Mode1"] == "" or Parameters["Mode2"] == "":
                Domoticz.Log("'Compte' et 'VIN' non renseignés, ")
                loop.run_until_complete(self.onAction())
                return
            loop.run_until_complete(self.onAction("update"))
            
    def onStart(self):
        Domoticz.Log("Start Renault/Dacia script")
        if (len(Devices) == 0):
            hardware_name = Parameters["Name"]
            Domoticz.Log(f"No devices found for {hardware_name}. Creating devices.")
            # Mesure
            Domoticz.Device(Name="Batterie", Unit=1, TypeName="Percentage", Used=1).Create()
            Domoticz.Device(Name="Temperature batterie", Unit=2, TypeName="Custom", Used=1, Options={'Custom': '1;°C'}).Create()
            Domoticz.Device(Name="Autonomie batterie", Unit=3, TypeName="Custom", Used=1, Options={'Custom': '1;km'}).Create()
            Domoticz.Device(Name="Energie batterie", Unit=4, TypeName="Custom", Used=1, Options={'Custom': '1;kWh'}).Create()
            Domoticz.Device(Name="Capacité batterie", Unit=5, TypeName="Custom", Used=1, Options={'Custom': '1;kWh'}).Create()
            # Unités 6 (Branchée) et 7 (Charge en cours) créées plus bas en Selector Switch (dropdown)
            Domoticz.Device(Name="Temps charge restant", Unit=8, TypeName="Text", Used=1).Create()
            Domoticz.Device(Name="Puissance de charge", Unit=9, TypeName="Custom", Used=1, Options={'Custom': '1;kWh'}).Create()
            Domoticz.Device(Name="Compteur km", Unit=10, Type=113, Subtype=0, Used=1, Switchtype=3).Create()
            Devices[10].Update(nValue=0, sValue=str(0)) # set default, if not set you make Domoticz crash
            Domoticz.Device(Name="Localisation", Unit=11, TypeName="Text", Used=1).Create()
            # Actionneur
            Domoticz.Device(Name="Mise à jour", Unit=12, TypeName="Switch", Used=1, Switchtype=9).Create()
            Domoticz.Device(Name="Lancer la charge", Unit=13, TypeName="Switch", Used=1, Switchtype=9).Create()
            Domoticz.Device(Name="Arrêter la charge", Unit=14, TypeName="Switch", Used=1, Switchtype=10).Create()            
            #Domoticz.Device(Name="Carburant autonomie", Unit=15, Type=243, Subtype=31, Used=0, Options={'Custom': '1;km'}).Create()    # not used
            #Domoticz.Device(Name="Carburant quantité", Unit=16, Type=243, Subtype=31, Used=0, Options={'Custom': '1;L'}).Create()      # not used
            Domoticz.Device(Name="Charge max programmée", Unit=17, TypeName="Switch", Used=1, Switchtype=18, Options={"LevelNames":"Off|20|30|40|50|60|70|80|90|100","LevelActions":"|","LevelOffHidden": "false","SelectorStyle": "1"}).Create() 

            #Domoticz.Device(Name="Lancer la clim", Unit=23, TypeName="Switch", Used=1, Switchtype=9).Create()
            #Domoticz.Device(Name="Arrêter la clim", Unit=24, TypeName="Switch", Used=1, Switchtype=9).Create()
            # faire des evennements si l'heure >xxx et charge < xx alors lancer la charge. Si charge > 80% alors arreter la charge, etc.
            Domoticz.Log(f"Devices created for {hardware_name} !")
        # Indicateurs "Branchée" (Unit 6) et "Charge en cours" (Unit 7) en Selector Switch (dropdown).
        # Créés/recréés hors du bloc ci-dessus pour permettre la migration : supprimez ces 2
        # dispositifs dans Domoticz puis redémarrez le plugin pour les recréer en sélecteurs.
        if 6 not in Devices:
            Domoticz.Device(
                Name="Branchée", Unit=6, TypeName="Selector Switch", Used=1,
                Options={"LevelActions": "|", "LevelNames": "Débranchée|Branchée",
                         "LevelOffHidden": "false", "SelectorStyle": "1"}
            ).Create()
        if 7 not in Devices:
            Domoticz.Device(
                Name="Charge en cours", Unit=7, TypeName="Selector Switch", Used=1,
                Options={"LevelActions": "||", "LevelNames": "Arrêtée|En charge|Erreur",
                         "LevelOffHidden": "false", "SelectorStyle": "1"}
            ).Create()
        copy2('./plugins/Dacia/Dacia.html', './www/templates/Dacia.html')
        os.mkdir('./www/templates/Dacia')
        copy2('./plugins/Dacia/icone/actualiser.png', './www/templates/Dacia/actualiser.png')
        copy2('./plugins/Dacia/icone/Arreter_charger.png', './www/templates/Dacia/Arreter_charger.png')
        copy2('./plugins/Dacia/icone/deprogrammer.png', './www/templates/Dacia/deprogrammer.png')
        copy2('./plugins/Dacia/icone/programmer.png', './www/templates/Dacia/programmer.png')
        copy2('./plugins/Dacia/icone/Recharger.png', './www/templates/Dacia/Recharger.png')
        
        copy2('./plugins/Dacia/Plugin_RenaultDacia_Programmer.lua', './scripts/dzVents/scripts/Plugin_RenaultDacia_Programmer.lua')
        copy2('./plugins/Dacia/Plugin_RenaultDacia_Selector.lua', './scripts/dzVents/scripts/Plugin_RenaultDacia_Selector.lua')
        
            
    def onStop(self):
        Domoticz.Log("onStop called")
        if (os.path.exists('./www/templates/Dacia.html')):
            os.remove('./www/templates/Dacia.html')
            os.remove('./www/templates/Dacia/actualiser.png')
            os.remove('./www/templates/Dacia/Arreter_charger.png')
            os.remove('./www/templates/Dacia/deprogrammer.png')
            os.remove('./www/templates/Dacia/programmer.png')
            os.remove('./www/templates/Dacia/Recharger.png')
            os.rmdir('./www/templates/Dacia')
            
            os.remove('./scripts/dzVents/scripts/Plugin_RenaultDacia_Programmer.lua')
            os.remove('./scripts/dzVents/scripts/Plugin_RenaultDacia_Selector.lua')
	
    def onConnect(self, Connection, Status, Description):
        Domoticz.Log("onConnect called")
	
    def onMessage(self, Connection, Data):
        Domoticz.Log("onMessage called")

    def onCommand(self, Unit, Command, Level, Hue):
        loop = asyncio.get_event_loop() 
        if Unit == 12:
            loop.run_until_complete(self.onAction("update"))
        if Unit == 13:
            loop.run_until_complete(self.onAction("startCharge"))
        if Unit == 14:
            loop.run_until_complete(self.onAction("stopCharge"))
	
    def onDisconnect(self, Connection):
        Domoticz.Log("onDisconnect called")

    def mustUpdate(self):
        if self._lastUpdate == None: 
            return True
        elapsedTime = int((datetime.now()-self._lastUpdate).total_seconds() / 60)  # time in minutes
        if elapsedTime >= self._updateInterval: 
            return True
        return False
        
    # Endpoint KCM des réglages de charge (Renault 5 E-Tech, etc.)
    EV_SETTINGS_ENDPOINT = (
        "/commerce/v1/accounts/{account_id}/kamereon/kcm/v1/vehicles/{vin}/ev/settings"
    )
    # Détection de l'arrêt effectif de la charge via le capteur de puissance Shelly.
    # Mesuré en réel : ~2350 W en charge, ~3 W à l'arrêt -> seuil 10 W largement suffisant.
    ZEROWATT_TIMEOUT = 120    # secondes max d'attente avant abandon
    ZEROWATT_INTERVAL = 8     # secondes entre deux lectures
    ZEROWATT_THRESHOLD = 10   # W : en dessous, la charge est considérée arrêtée
    SHELLY_ON_DELAY = 3       # secondes d'attente après allumage du relais (retour du courant)
    # API JSON locale de Domoticz : l'hôte est toujours la machine locale ;
    # le port de l'interface web est auto-détecté (pas de champ à configurer).
    DOMOTICZ_HOST = "127.0.0.1"
    DOMOTICZ_PORT_CANDIDATES = ("8080", "80")

    async def stopCharge(self, vehicle, websession, hardware_name):
        """Arrête la charge.

        Zoé/Spring/etc. : arrêt standard via set_charge_stop().

        Renault 5 E-Tech (R5E1VE) et autres véhicules KCM : renault-api mappe
        'actions/charge-stop' à None (commentaire de la lib : "Not supported -
        use charger to stop") et 'charge/pause-resume' renvoie
        'err.func.wired.forbidden' (testé en réel sur cette R5). Comme dans
        l'appli MyRenault (aucun bouton "stop" direct), on arrête la charge en
        ACTIVANT le planning de charge, puis on coupe proprement le courant :

        Séquence validée en conditions réelles sur R5 E-Tech :
        1. Activer UN programme de charge -> la charge s'arrête (~3 W).
        2. Attendre que le capteur Shelly (IDX Mode6) passe sous 10 W.
        3. COUPER le relais Shelly (IDX SerialPort) -> AVANT de désactiver
           le planning. C'est indispensable : désactiver le planning alors que
           le courant est présent RELANCE immédiatement la charge (constaté).
        4. Désactiver/restaurer le planning (plus de courant -> pas de relance).
        """
        try:
            resp = await vehicle.set_charge_stop()
            Domoticz.Log(f"Charge arrêtée pour {hardware_name} (set_charge_stop). Réponse : {resp}")
        except EndpointNotAvailableError as err:
            Domoticz.Log(
                f"Arrêt standard indisponible pour ce modèle ({err}) : "
                f"arrêt via planning + coupure Shelly (véhicule KCM type R5)."
            )
            await self._stopChargeViaSchedule(vehicle, websession, hardware_name)

    async def _stopChargeViaSchedule(self, vehicle, websession, hardware_name):
        """Arrête la charge d'un véhicule KCM (R5) : planning ON -> 0 W -> Shelly OFF -> planning restauré."""
        resp = await vehicle.http_get(self.EV_SETTINGS_ENDPOINT)
        settings = resp.raw_data
        programs = settings.get("programs") or []
        if not programs:
            Domoticz.Error(
                f"Aucun programme de charge sur {hardware_name} : impossible d'arrêter "
                f"la charge via le planning. Arrêtez la charge côté borne/véhicule."
            )
            return
        original_status = [p.get("programActivationStatus", False) for p in programs]

        # 1. Activer UN seul programme suffit à arrêter la charge en cours.
        programs[0]["programActivationStatus"] = True
        await vehicle.http_post(self.EV_SETTINGS_ENDPOINT, settings)
        Domoticz.Log(
            f"Planning de charge activé pour {hardware_name} -> arrêt de charge demandé."
        )

        # 2. Attendre l'arrêt effectif (puissance < seuil).
        stopped = await self._waitForZeroWatt(websession, hardware_name)
        if not stopped:
            # Charge non confirmée arrêtée : NE PAS couper le relais (coupure
            # "sauvage" en pleine charge) et laisser le planning actif pour que
            # la charge reste stoppée. Intervention manuelle possible.
            Domoticz.Error(
                f"Arrêt non confirmé pour {hardware_name} (puissance toujours élevée) : "
                f"relais Shelly NON coupé et planning laissé ACTIF pour maintenir l'arrêt. "
                f"Vérifiez le véhicule/la borne."
            )
            return

        # 3. Couper le relais Shelly AVANT de désactiver le planning.
        await self._setShellySwitch(websession, "Off", hardware_name)

        # 4. Restaurer l'état initial du planning (désactivation). Plus de
        #    courant -> aucune relance de charge.
        resp2 = await vehicle.http_get(self.EV_SETTINGS_ENDPOINT)
        settings2 = resp2.raw_data
        for p, orig in zip(settings2.get("programs") or [], original_status):
            p["programActivationStatus"] = orig
        await vehicle.http_post(self.EV_SETTINGS_ENDPOINT, settings2)
        Domoticz.Log(
            f"Charge arrêtée proprement pour {hardware_name} : relais coupé puis planning restauré."
        )

    async def _detectDomoticzPort(self, websession):
        """Auto-détecte le port de l'API web Domoticz locale (mis en cache)."""
        if self._domoticzPort:
            return self._domoticzPort
        for port in self.DOMOTICZ_PORT_CANDIDATES:
            url = f"http://{self.DOMOTICZ_HOST}:{port}/json.htm?type=command&param=getversion"
            try:
                async with websession.get(url, timeout=aiohttp.ClientTimeout(total=5)) as r:
                    data = await r.json(content_type=None)
            except Exception:
                continue
            if isinstance(data, dict) and data.get("status") == "OK":
                self._domoticzPort = port
                Domoticz.Log(f"API Domoticz détectée sur {self.DOMOTICZ_HOST}:{port}.")
                return port
        Domoticz.Error(
            f"API web Domoticz introuvable sur {self.DOMOTICZ_HOST} "
            f"(ports testés : {', '.join(self.DOMOTICZ_PORT_CANDIDATES)}). "
            f"Lecture/pilotage Shelly impossible."
        )
        return None

    async def _domoticzApiGet(self, websession, params):
        """Appelle l'API JSON locale de Domoticz (hôte local, port auto-détecté)."""
        port = await self._detectDomoticzPort(websession)
        if not port:
            return None
        url = f"http://{self.DOMOTICZ_HOST}:{port}/json.htm?{params}"
        try:
            async with websession.get(url, timeout=aiohttp.ClientTimeout(total=10)) as r:
                return await r.json(content_type=None)
        except Exception as e:
            Domoticz.Error(f"Appel API Domoticz échoué ({params}) : {e}")
            return None

    async def _readDeviceField(self, websession, idx, field):
        """Lit un champ (ex: 'Usage', 'Status') d'un device Domoticz par son IDX."""
        if not idx:
            return None
        data = await self._domoticzApiGet(websession, f"type=command&param=getdevices&rid={idx}")
        if not data:
            return None
        result = data.get("result") or []
        if not result:
            return None
        return result[0].get(field)

    async def _readChargeWatts(self, websession):
        """Lit la puissance de charge (W) depuis le capteur Shelly (IDX Mode6)."""
        usage = await self._readDeviceField(websession, Parameters["Mode6"], "Usage")
        if usage is None:
            return None
        try:
            return float(str(usage).strip().split()[0])  # ex: "0 Watt" -> 0.0
        except (ValueError, IndexError):
            return None

    async def _setShellySwitch(self, websession, cmd, hardware_name):
        """Commute le relais Shelly (IDX Address). cmd = 'On' ou 'Off'."""
        idx = Parameters["Address"]
        if not idx:
            Domoticz.Error(
                f"Aucun IDX relais Shelly configuré pour {hardware_name} : "
                f"le courant n'a pas pu être commuté ({cmd})."
            )
            return False
        data = await self._domoticzApiGet(
            websession, f"type=command&param=switchlight&idx={idx}&switchcmd={cmd}"
        )
        if not data or data.get("status") != "OK":
            Domoticz.Error(f"Commutation relais Shelly (IDX {idx}) -> {cmd} échouée.")
            return False
        Domoticz.Log(f"Relais Shelly (IDX {idx}) commuté sur {cmd} pour {hardware_name}.")
        return True

    async def _ensureShellyOn(self, websession, hardware_name):
        """Allume le relais Shelly s'il est éteint (courant requis pour charger)."""
        idx = Parameters["Address"]
        if not idx:
            return  # relais non piloté : on suppose le courant déjà présent
        status = await self._readDeviceField(websession, idx, "Status")
        if status is not None and str(status).lower() == "on":
            Domoticz.Log(f"Relais Shelly (IDX {idx}) déjà allumé pour {hardware_name}.")
            return
        if await self._setShellySwitch(websession, "On", hardware_name):
            await asyncio.sleep(self.SHELLY_ON_DELAY)  # laisser le courant s'établir

    async def _waitForZeroWatt(self, websession, hardware_name):
        """Attend que la puissance de charge retombe sous le seuil (capteur Shelly).

        Retourne True si l'arrêt est confirmé, False en cas de timeout ou
        d'absence de capteur configuré.
        """
        idx = Parameters["Mode6"]
        if not idx:
            Domoticz.Error(
                "Aucun IDX capteur puissance (Mode6) configuré : impossible de confirmer "
                "l'arrêt de charge. Le relais ne sera pas coupé automatiquement."
            )
            return False
        waited = 0
        while waited < self.ZEROWATT_TIMEOUT:
            watts = await self._readChargeWatts(websession)
            Domoticz.Log(f"Attente arrêt charge {hardware_name} : {watts} W (IDX {idx})")
            if watts is not None and watts < self.ZEROWATT_THRESHOLD:
                Domoticz.Log(f"Puissance < {self.ZEROWATT_THRESHOLD} W : charge arrêtée pour {hardware_name}.")
                return True
            await asyncio.sleep(self.ZEROWATT_INTERVAL)
            waited += self.ZEROWATT_INTERVAL
        return False

    async def onAction(self, Action='update'):
        # Création de la session
        async with aiohttp.ClientSession() as websession:
            client = RenaultClient(websession=websession, locale="fr_FR")
            await client.session.login(Parameters["Username"], Parameters["Password"])
            
            # Connexion au compte
            account = await client.get_api_account(Parameters["Mode1"])
            # Verification si le compte existe, sinon on renvoi les informations trouvées avec les paramètres nom d'utilisateur et mot de passe, et on arrête là.
            if account.account_id == "":
                accountList = await client.get_api_accounts()
                Domoticz.Log("Recherche des comptes associés aux indentifiants...")
                if len(accountList) == 0:
                    Domoticz.Log("Aucun compte trouvé. Vérifiez 'Email' et 'Mot de passe' dans les paramètres du Plugin (Hardware)")
                    return
                Domoticz.Log("Des comptes et VIN associés à votre login/pass ont été trouvés. Entrez les numéro de 'Compte' et 'VIN' dans les paramètres du Plugin(Hardware).")
                for i in range(len(accountList)):
                    Domoticz.Log(f"  {i} - Compte: {accountList[i].account_id}")
                    vehiclesList = await accountList[i].get_api_vehicles()
                    if len(vehiclesList) == 0:
                        Domoticz.Log(f"   \t   Pas de véhicule pour le compte {i}")
                    for j in range(len(vehiclesList)):
                        response = await vehiclesList[j].get_details()
                        Domoticz.Log(f"  \t\t\t    {i}.{j} - VIN:{response.vin} - Marque:{response.raw_data['brand']['label']} - Modèle:{response.raw_data['model']['label']}")
                return
                
            # Récupération de l'objet Vehicle
            vehicle = await account.get_api_vehicle(Parameters["Mode2"])
            if vehicle.vin == "":
                usrVin = Parameters["Mode2"]
                Domoticz.Log(f"Véhicule avec le VIN {usrVin} non trouvé. Vérifiez les paramètres du Plugin (Hardware).")
                vehiclesList = await account.get_api_vehicles()
                Domoticz.Log("Recherche des VIN associés au compte...")
                if len(vehiclesList) == 0:
                    Domoticz.Log(f"   \t   Pas de véhicule pour le compte {account.account_id}")
                for k in range(len(vehiclesList)):
                    response = await vehiclesList[k].get_details()
                    Domoticz.Log(f"  \t\t\t    {k} - VIN:{response.vin} - Marque:{response.raw_data['brand']['label']} - Modèle:{response.raw_data['model']['label']}")
                return
            Domoticz.Log("Véhicule trouvé !")
            self._vehicle = vehicle
            
            # Mise à jour des devices (toujours effectuée en amont des autres actions possibles)
            Battery_capacity = Parameters["Mode3"] # La capacité de la batterie doit être indiquée manuellement car l'API retourne 0
            if Parameters["Mode5"] == "111" or Parameters["Mode5"] == "010" or Parameters["Mode5"] == "011" or Parameters["Mode5"] == "110":
                Battery = await vehicle.get_battery_status()
                Domoticz.Log("Battery status ok")
                self._Battery = Battery
                Battery_level = Battery.batteryLevel #int
                Battery_temperature = Battery.batteryTemperature #int
                Battery_autonomy = Battery.batteryAutonomy #int
                Battery_availableEnergy = Battery.batteryAvailableEnergy #int
                Battery_plugStatus = Battery.plugStatus #int
                Battery_chargingStatus = Battery.chargingStatus #float
                Battery_chargingRemainingTime = Battery.chargingRemainingTime #int
                Battery_chargingInstantaneousPower = Battery.chargingInstantaneousPower #int
                Domoticz.Log(f"Battery level : {Battery_level}%")
                Domoticz.Log(f"Battery temperature : {Battery_temperature}°C")
                Domoticz.Log(f"Battery autonomy : {Battery_autonomy} km")
                Domoticz.Log(f"Battery available energy : {Battery_availableEnergy} kWh")
                Domoticz.Log(f"Battery capacity : {Battery_capacity} kWh")
                Domoticz.Log(f"Plug status : {Battery_plugStatus}")
                Domoticz.Log(f"Charging status : {Battery_chargingStatus}")
                Domoticz.Log(f"Charging remaining time : {Battery_chargingRemainingTime} ??")
                Domoticz.Log(f"Instantaneous Power : {Battery_chargingInstantaneousPower} kWh")
                Devices[1].Update(nValue=0, sValue=str(Battery_level)) # Battery percentage
                Devices[2].Update(nValue=0, sValue=str(Battery_temperature)) # Battery temperature
                Devices[3].Update(nValue=0, sValue=str(Battery_autonomy)) # Battery autonomy
                Devices[4].Update(nValue=0, sValue=str(Battery_availableEnergy)) # Battery energy
                Devices[5].Update(nValue=0, sValue=str(Battery_capacity)) # Battery capacity
                # Selector "Branchée" : 0=Débranchée, 10=Branchée
                plug_level = 10 if int(Battery_plugStatus) == 1 else 0
                Devices[6].Update(nValue=(2 if plug_level else 0), sValue=str(plug_level))
                # Selector "Charge en cours" : 0=Arrêtée, 10=En charge, 20=Erreur
                cs = float(Battery_chargingStatus)
                charge_level = 20 if cs < 0 else (10 if cs >= 1 else 0)
                Devices[7].Update(nValue=(2 if charge_level else 0), sValue=str(charge_level))
                Devices[8].Update(nValue=0, sValue=str(Battery_chargingRemainingTime)) # Battery remaining charging time - color may be changed by nvalue (0=gray, 1=green, 2=yellow, 3=orange, 4=red)
                Devices[9].Update(nValue=0, sValue=str(Battery_chargingInstantaneousPower)) # Battery charging power
            if Parameters["Mode5"] == "111" or Parameters["Mode5"] == "100" or Parameters["Mode5"] == "101" or Parameters["Mode5"] == "110":
                Cockpit = await vehicle.get_cockpit()
                Domoticz.Log("Cockpit ok")
                self._Cockpit = Cockpit
                totalMileage = Cockpit.totalMileage #float
                Domoticz.Log(f"Total mileage : {totalMileage} km")
                Devices[10].Update(nValue=0, sValue=str(totalMileage)) # Total mileage
            if Parameters["Mode5"] == "111" or Parameters["Mode5"] == "001" or Parameters["Mode5"] == "101" or Parameters["Mode5"] == "011":
                Location = await vehicle.get_location()
                Domoticz.Log("Location ok")
                self._Location = Location
                latitude = Location.gpsLatitude #float
                longitude = Location.gpsLongitude #float
                Domoticz.Log(f"Latitude : {latitude}")
                Domoticz.Log(f"Longitude : {longitude}")
                Devices[11].Update(nValue=0, sValue="Latitude : "+str(latitude)+" / Longitude : "+str(longitude)) # Position 
            
            # Traitement de l'Action
            hardware_name = Parameters["Name"]
            if Action == "update":
                # Rien de plus à effectuer
                return
            elif Action == "startCharge":
                if Battery_plugStatus == 1:
                    # Le courant doit être présent : on allume le relais Shelly
                    # s'il est éteint (il l'est hors de sa plage programmée),
                    # puis on lance la charge via l'API officielle.
                    await self._ensureShellyOn(websession, hardware_name)
                    Domoticz.Log(f"Lancement de la charge de {hardware_name}.")
                    await vehicle.set_charge_start()
                return
            elif Action == "stopCharge":
                if Battery_plugStatus == 1:
                    Domoticz.Log(f"Arrêt de la charge de {hardware_name}.")
                    await self.stopCharge(vehicle, websession, hardware_name)
                return
            else:
                return
                
                
global _plugin
_plugin = BasePlugin()

def onStart():
    global _plugin
    _plugin.onStart()

def onStop():
    global _plugin
    _plugin.onStop()

def onConnect(Connection, Status, Description):
    global _plugin
    _plugin.onConnect(Connection, Status, Description)

def onMessage(Connection, Data):
    global _plugin
    _plugin.onMessage(Connection, Data)

def onCommand(Unit, Command, Level, Hue):
    global _plugin
    _plugin.onCommand(Unit, Command, Level, Hue)

def onNotification(Name, Subject, Text, Status, Priority, Sound, ImageFile):
    global _plugin
    _plugin.onNotification(Name, Subject, Text, Status, Priority, Sound, ImageFile)

def onDisconnect(Connection):
    global _plugin
    _plugin.onDisconnect(Connection)

def onHeartbeat():
    global _plugin
    _plugin.onHeartbeat()

# Generic helper functions
def DumpConfigToLog():
    for x in Parameters:
        if Parameters[x] != "":
            Domoticz.Debug( "'" + x + "':'" + str(Parameters[x]) + "'")
    Domoticz.Debug("Device count: " + str(len(Devices)))
    for DeviceName in Devices:
        Device = Devices[DeviceName]
        Domoticz.Debug("Device ID:       '" + str(Device.DeviceID) + "'")
        Domoticz.Debug("--->Unit Count:      '" + str(len(Device.Units)) + "'")
        for UnitNo in Device.Units:
            Unit = Device.Units[UnitNo]
            Domoticz.Debug("--->Unit:           " + str(UnitNo))
            Domoticz.Debug("--->Unit Name:     '" + Unit.Name + "'")
            Domoticz.Debug("--->Unit nValue:    " + str(Unit.nValue))
            Domoticz.Debug("--->Unit sValue:   '" + Unit.sValue + "'")
            Domoticz.Debug("--->Unit LastLevel: " + str(Unit.LastLevel))
    return
