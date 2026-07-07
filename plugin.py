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
<plugin key="domoticz-renault-dacia" name="Renault / Dacia connect" author="Richeux" version="1.0.2" wikilink="https://github.com/lemassykoi/Domoticz-Renault-Dacia-Plugin" externallink="https://renault-api.readthedocs.io/en/latest/index.html">
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
            Domoticz.Device(Name="Branchée", Unit=6, TypeName="Custom", Used=1, Options={'Custom': '1;Plug'}).Create()
            Domoticz.Device(Name="Charge en cours", Unit=7, TypeName="Custom", Used=1, Options={'Custom': '1;Charge'}).Create()
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
        
    async def stopCharge(self, vehicle, hardware_name):
        """Arrête (met en pause) la charge.

        Sur les véhicules KCM récents (Renault 5 E-Tech = R5E1VE, R4 E-Tech,
        Twingo, Scenic E-Tech...), renault-api mappe 'actions/charge-stop' à None :
        set_charge_stop() lève alors EndpointNotAvailableError
        ("Endpoint 'actions/charge-stop' not available for model 'R5E1VE'").
        Ces véhicules utilisent l'endpoint KCM 'charge/pause-resume'. On bascule
        donc sur un POST direct de l'action 'pause' vers cet endpoint.
        """
        try:
            await vehicle.set_charge_stop()
            Domoticz.Log(f"Charge arrêtée pour {hardware_name} (set_charge_stop).")
        except EndpointNotAvailableError as err:
            Domoticz.Log(
                f"'set_charge_stop' indisponible pour ce modèle ({err}). "
                f"Bascule sur l'endpoint KCM 'charge/pause-resume' (action pause)..."
            )
            endpoint = (
                "/commerce/v1/accounts/{account_id}/kamereon"
                "/kcm/v1/vehicles/{vin}/charge/pause-resume"
            )
            body = {
                "data": {
                    "type": "ChargePauseResume",
                    "attributes": {"action": "pause"},
                }
            }
            await vehicle.http_post(endpoint, body)
            Domoticz.Log(
                f"Commande 'pause' envoyée pour {hardware_name} (KCM charge/pause-resume)."
            )

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
                Devices[6].Update(nValue=0, sValue=str(Battery_plugStatus)) # Battery plugged
                Devices[7].Update(nValue=0, sValue=str(Battery_chargingStatus)) # Battery charging
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
                    Domoticz.Log(f"Lancement de la charge de {hardware_name}.")
                    await vehicle.set_charge_start()
                return
            elif Action == "stopCharge":
                if Battery_plugStatus == 1:
                    Domoticz.Log(f"Arrêt de la charge de {hardware_name}.")
                    await self.stopCharge(vehicle, hardware_name)
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
