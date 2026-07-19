# Domoticz-Renault-Dacia-Plugin
Plugin Domoticz afin d'obtenir les informations et piloter votre véhicule électrique Renault ou Dacia.

## Nouveautés de ce fork (compatibilité Renault 5 E-Tech)

Ce fork ([lemassykoi/Domoticz-Renault-Dacia-Plugin](https://github.com/lemassykoi/Domoticz-Renault-Dacia-Plugin)) ajoute la prise en charge des véhicules **KCM** récents de Renault, en particulier la **Renault 5 E-Tech** (code modèle `R5E1VE`). Objectif à terme : couvrir aussi la **R4 E-Tech** (`A4E1VE`) et la **Twingo** (`X071VE`).

### Ce qui est corrigé / ajouté

| Fonction | Avant (R5) | Après ce fork |
|----------|-----------|---------------|
| Relevé SoC / batterie | ✅ | ✅ |
| Kilométrage (cockpit) | ✅ | ✅ |
| Localisation GPS | ✅ | ✅ |
| Lancement de charge | ✅ | ✅ (allume le relais Shelly puis lance la charge) |
| **Arrêt de charge** | ❌ `Endpoint 'actions/charge-stop' not available for model 'R5E1VE'` | ✅ **validé en réel** (planning → 0 W → coupure relais) |
| **Recharge programmée** | ❌ (l'arrêt planifié plantait) | ✅ *(dépend de l'arrêt de charge)* |
| Affichage *Branchée* / *Charge en cours* | Capteur texte | **Liste déroulante** (Selector Switch) |
| Intervalle mini de polling | 10 min | **5 min** |

### Pourquoi l'arrêt de charge plantait

La R5 est un véhicule de génération **KCM**. Dans la bibliothèque `renault-api`, le modèle `R5E1VE` déclare explicitement l'action d'arrêt comme indisponible :

```python
"R5E1VE": {  # Renault 5 E-TECH
    "actions/charge-start": _KCM_ENDPOINTS["actions/charge-start-via-settings"],  # ev/settings
    "actions/charge-stop": None,  # Not supported - use charger to stop
    ...
}
```

Résultat : l'appel `vehicle.set_charge_stop()` lève `EndpointNotAvailableError` **avant même d'envoyer une requête**, d'où l'erreur mentionnant `R5E1VE`. Comme la « recharge programmée » du plugin met simplement en file un ordre d'arrêt (via dzVents) en fin de créneau, elle échouait pour la même raison.

### Ce qui NE fonctionne PAS pour arrêter la charge (testé en réel sur la R5)

- **`set_charge_stop()` (High-level API)** : échoue avant tout appel réseau (mapping `None`).
- **Endpoint KCM `charge/pause-resume` (action `pause`)** : renvoie `('err.func.wired.forbidden', 'The access is forbidden')`. Testé directement :
  ```
  renault-api http post \
    "/commerce/v1/accounts/{account_id}/kamereon/kcm/v1/vehicles/{vin}/charge/pause-resume" \
    '{"data":{"type":"ChargePauseResume","attributes":{"action":"pause"}}}'
  # -> Error: ('err.func.wired.forbidden', 'The access is forbidden')
  ```
  Le commentaire de la lib (« use charger to stop ») est donc exact : **il n'existe pas d'ordre d'arrêt direct** pour la R5, comme le confirme l'appli MyRenault qui n'a **aucun bouton « stop »**.

### Comment l'arrêt est réellement obtenu (mécanisme reproduit)

Dans MyRenault, pour arrêter une charge en cours on **active le planning de charge** (la voiture n'accepte alors de charger qu'à l'heure programmée → la charge en cours s'arrête), puis on coupe le courant. Ce fork reproduit exactement ce comportement, **validé en conditions réelles sur la R5** :

```
ARRÊT DE CHARGE (R5 / véhicules KCM sans charge-stop)
┌────────────────────────────────────────────────────────────┐
│ 1. Activer UN programme de charge (POST ev/settings)         │
│    programActivationStatus = true  ->  la charge s'arrête    │
│ 2. Attendre que le capteur Shelly (IDX puissance) passe      │
│    sous 10 W (mesuré : ~2350 W en charge, ~3 W à l'arrêt)    │
│ 3. COUPER le relais Shelly (IDX interrupteur)  ← AVANT !     │
│ 4. Désactiver / restaurer le planning (POST ev/settings)     │
│    plus de courant -> aucune relance de charge               │
└────────────────────────────────────────────────────────────┘
```

> ⚠️ **L'ordre est critique.** Il faut **couper le relais Shelly AVANT de désactiver le planning**. Désactiver le planning alors que le courant est encore présent **relance immédiatement la charge** (constaté en réel). C'est pour cela que le plugin a besoin de piloter le relais Shelly, et pas seulement de lire sa mesure de puissance.

Le **démarrage** de charge, lui, fonctionne nativement en mode `kcm-settings` (désactivation des programmes planifiés → charge immédiate). Le plugin **allume d'abord le relais Shelly** (le courant est coupé hors de sa plage programmée) puis appelle `set_charge_start()`.

### Rôle du Shelly (mesure + relais)

Le Shelly sert à deux choses, via **deux IDX Domoticz distincts** :

| IDX (à configurer) | Rôle | Utilisation par le plugin |
|--------------------|------|---------------------------|
| **Capteur puissance** (`Mode6`) | Mesure la puissance de charge (W) | Lecture seule, pour détecter l'arrêt effectif (< 10 W) |
| **Relais / interrupteur** (`SerialPort`) | Coupe/donne le courant à la borne | Allumé au démarrage ; **coupé après** l'arrêt (une fois à 0 W) |

Le but est de **ne plus couper « sauvagement » le courant** en pleine charge : on arrête d'abord la charge proprement via l'API Renault (retour à ~0 W), **puis** on coupe le relais. Si l'arrêt n'est pas confirmé (timeout, puissance toujours élevée), le plugin **ne coupe pas** le relais et **laisse le planning actif** (la charge reste stoppée), et journalise une erreur.

### Nouveaux paramètres de configuration (Hardware)

À renseigner dans *Configuration → Matériel* sur le plugin :

| Champ | Description | Exemple |
|-------|-------------|---------|
| **IDX capteur puissance** (`Mode6`) | IDX du dispositif Domoticz mesurant la puissance de charge (Shelly) | `29` |
| **IDX relais Shelly** (`SerialPort`) | IDX de l'interrupteur/relais Shelly qui coupe le courant | `28` |
| **IP API Domoticz locale** (`Address`) | IP de l'API JSON Domoticz | `127.0.0.1` |
| **Port API Domoticz locale** (`Port`) | Port de l'interface web Domoticz | `8080` ou `80` |

> ℹ️ Le **port** est celui de l'**interface web** de Domoticz (souvent `8080`, mais `80` sur certaines installations). Vérifiez-le : le plugin interroge `http://<Address>:<Port>/json.htm?...`.

> ℹ️ Si `IDX relais Shelly` (`SerialPort`) n'est **pas** renseigné, le plugin ne pilote pas le courant (il suppose le courant présent) : le démarrage n'allumera rien et l'arrêt ne coupera rien. Si `IDX capteur puissance` (`Mode6`) n'est pas renseigné, l'arrêt R5 **ne peut pas être confirmé** et le relais n'est pas coupé.

### Migration des dispositifs « Branchée » et « Charge en cours »

Ces deux dispositifs passent de *capteur texte* à **liste déroulante** (Selector Switch) :

- **Branchée** : `Débranchée` / `Branchée`
- **Charge en cours** : `Arrêtée` / `En charge` / `Erreur`

Sur une installation **existante**, ces dispositifs ne sont **pas** recréés automatiquement (Domoticz conserve les anciens). Pour bénéficier des listes déroulantes :

1. Dans Domoticz, supprimer les deux dispositifs **Branchée** (Unité 6) et **Charge en cours** (Unité 7).
2. Redémarrer le plugin (ou Domoticz). Ils seront recréés en Selector Switch.

Sur une **nouvelle** installation, ils sont créés directement en listes déroulantes.

### Comment tester l'arrêt de charge

1. Assurez-vous que le véhicule est **branché**, que le **relais Shelly est allumé** et que la **charge est en cours** (*Branchée* = Branchée, *Charge en cours* = En charge, capteur puissance ~2 kW).
2. Surveillez le journal du plugin dans Domoticz.
3. Appuyez sur le dispositif **Arrêter la charge**.
4. Séquence attendue dans les logs :
   - `Arrêt standard indisponible pour ce modèle (...) : arrêt via planning + coupure Shelly (véhicule KCM type R5).`
   - `Planning de charge activé pour <nom> -> arrêt de charge demandé.`
   - plusieurs lignes `Attente arrêt charge <nom> : <W> W (IDX ...)` jusqu'à passer sous 10 W
   - `Relais Shelly (IDX ...) commuté sur Off pour <nom>.`
   - `Charge arrêtée proprement pour <nom> : relais coupé puis planning restauré.`
5. Vérifiez que la puissance reste à ~0 W (pas de relance) et l'arrêt dans MyRenault.

En cas d'échec (`Arrêt non confirmé...`), la charge est laissée stoppée par le planning (relais non coupé) : vérifiez le véhicule/la borne, puis coupez éventuellement le relais manuellement.

### Fréquence d'actualisation et quota API

L'API Kamereon de Renault **limite le nombre de requêtes à ~60 par heure** (au-delà : `err.func.wired.overloaded` / « You have reached your quota limit »). C'est une limite **côté serveur Renault**, indépendante du plugin.

Une option **5 minutes** a été ajoutée (l'intervalle minimum était de 10 min).

Estimation du coût par cycle selon le mode « Services actifs » choisi (≈ 1 requête de résolution du véhicule + 1 requête par service) :

| Mode « Services actifs » | Requêtes/cycle (approx.) | À 5 min (12 cycles/h) | À 10 min (6 cycles/h) |
|--------------------------|:------------------------:|:---------------------:|:---------------------:|
| Cockpit + Batterie + Localisation (`111`) | ~4 | ~48/h | ~24/h |
| Cockpit + Batterie (`110`) | ~3 | ~36/h | ~18/h |
| Batterie seule (`010`) | ~2 | ~24/h | ~12/h |

⚠️ À 5 min en mode complet (`111`) on est **sous le plafond mais serré** : chaque commande manuelle (Mise à jour / Lancer / Arrêter la charge) déclenche un rafraîchissement complet qui consomme des requêtes supplémentaires. **En cas d'erreurs de quota**, augmentez l'intervalle ou réduisez les « Services actifs ».

### Limites connues

- L'arrêt de charge R5 **dépend du Shelly** (mesure de puissance + relais). Sans ces deux IDX configurés, l'arrêt automatique propre n'est pas possible.
- Le seuil de détection d'arrêt est fixé à **10 W** (constantes `ZEROWATT_THRESHOLD`, `ZEROWATT_TIMEOUT=120s`, `ZEROWATT_INTERVAL=8s` dans `plugin.py`). Adaptez si votre borne consomme davantage en veille.
- Pendant l'arrêt, le plugin **attend** le retour à ~0 W (jusqu'à 120 s) : la commande *Arrêter la charge* peut donc prendre jusqu'à ~2 min avant de rendre la main.
- La « recharge programmée » du plugin est gérée **côté Domoticz** (dzVents planifie un ON puis un OFF), et non via l'API de planification native Renault. Elle dépend donc du bon fonctionnement des ordres de lancement/arrêt.
- R4 E-Tech et Twingo ne sont **pas encore testées** ; le mécanisme (planning + relais) devrait s'appliquer si leur `actions/charge-stop` est aussi `None` et qu'elles exposent `ev/settings`.

## Prérequis
La voiture doit être connectée à internet et disponible via les appli officielles de Renault ou Dacia.

L'API Renault-api https://renault-api.readthedocs.io/en/latest/ doit être installée (la configuration n'est pas nécessaire mais vous permet d'afficher votre account-id et le VIN).

L'API Renault-api doit être dans un répertoire accessible par Domoticz.


Avant d'intaller dans Domoticz, essayer de lancer un renault-api status pour vérifier quelles informations remontent correctement.

## Installation et configuration
### Installation
Cloner le dépôt dans le répertoire <i>plugins</i> de votre installation Domoticz :

Par exemple sous debian :

<code>cd chemin_domoticz/plugins
 git clone https://github.com/lemassykoi/Domoticz-Renault-Dacia-Plugin</code>

> Note : ce dépôt est un fork de [Kask29/Domoticz-Renault-Dacia-Plugin](https://github.com/Kask29/Domoticz-Renault-Dacia-Plugin) ajoutant la compatibilité Renault 5 E-Tech (voir « Nouveautés de ce fork » ci-dessus).

### Configuration
Dans <i>Domoticz / Configuration / Matériel</i> --> ajouter le plugin de type <i>Renault / Dacia connect</i> en le nommant par exemple <b>Spring</b> et rentrez les informations nécessaires à son fonctionnement :
- email du compte Renault ou Dacia
- mot de passe du compte Renault ou Dacia
- Account id (votre account id peut être trouvé via l'API Renault en faisant : <code>renault-api accounts</code>
- VIN (communiqué par le vendeur, sur la carte grise, dans l'appli puis Informations)
- La capacité de la batterie (afin d'estimer les temps de charge)
- La fréquence d'actualisation des dispositifs
![image](https://github.com/Kask29/Domoticz-Renault-Dacia-Plugin/assets/98609356/9f06d1cf-8e75-4905-88ab-08e0b9a5cff9)


Une fois ajouté, le plugin va créer seul :
- les Dispositifs nécessaires disponibles dans Interrupteurs et Mesures (ne pas les renommer, ni les supprimer, ni les mettre en non-utilisé. Pour les masquer, mettez les en <i>$Hidden</i> depuis <i>Plan</i>) :
![image](https://user-images.githubusercontent.com/98609356/229288896-56fa6ab4-62df-4cf7-88b2-3865c087a7d9.png)
![image](https://user-images.githubusercontent.com/98609356/229289047-854ee78b-bed2-44c8-a70c-5bc72ca0bf19.png)
- le dzEvent qui permet de programmer la charge (départ et arrêt à un moment donné, avec estimation de la charge obtenue)
- la page web qui permet de créer la tâche planifiée (disponible dans les pages personnalisée, pensez à activer l'onglet)
![image](https://user-images.githubusercontent.com/98609356/229289207-134981ef-6f78-458a-8f0b-422041f6c62a.png)


Toute nouvelle planification annule la planifiation précédente.

La planification n'est valable qu'une seule fois, mais rien ne vous empêche de créer vos scénarios personnalisés (comme habituellement avec Domoticz) basés sur les dispositifs du plugin.

## Changelog

### v1.1.0 (fork lemassykoi) — arrêt de charge R5 validé en réel

- **Arrêt de charge Renault 5 E-Tech (`R5E1VE`) fonctionnel, testé en conditions réelles** sur le véhicule :
  - Constaté que `set_charge_stop()` **et** l'endpoint KCM `charge/pause-resume` (action `pause`, `err.func.wired.forbidden`) **ne fonctionnent pas** sur la R5. L'approche `pause-resume` de la v1.0.2 est **abandonnée**.
  - Nouveau mécanisme reproduisant MyRenault : **activer un programme de charge** (`ev/settings`) pour arrêter la charge, **attendre 0 W** (capteur Shelly), **couper le relais Shelly**, puis **désactiver le planning**.
  - Ordre critique : coupure du relais **avant** désactivation du planning (sinon la charge redémarre — constaté).
  - Sécurité : si l'arrêt n'est pas confirmé (timeout / puissance élevée), le relais **n'est pas coupé** et le planning reste actif ; erreur journalisée.
- **Démarrage de charge** : allume désormais le relais Shelly (s'il est éteint) avant `set_charge_start()`.
- **Pilotage/lecture du Shelly** via l'API JSON locale de Domoticz. Nouveaux paramètres : `Mode6` (IDX capteur puissance), `SerialPort` (IDX relais), `Address`, `Port`.
- **Dispositifs *Branchée* et *Charge en cours*** convertis de capteur texte en **listes déroulantes** (Selector Switch). Voir la section migration.
- Option de fréquence d'actualisation **5 minutes** (minimum précédent : 10 min).
- Documentation entièrement mise à jour : mécanisme réel, rôle du Shelly, paramètres, migration, procédure de test, quota API, limites.

### v1.0.2 (fork lemassykoi) — obsolète
- Tentative d'arrêt R5 via bascule KCM `charge/pause-resume`. **Non fonctionnel sur la R5** (`err.func.wired.forbidden`), remplacé en v1.1.0.
- Ajout de l'option **5 minutes** ; documentation quota API.

### v1.0.1 et antérieures
Voir le dépôt d'origine [Kask29/Domoticz-Renault-Dacia-Plugin](https://github.com/Kask29/Domoticz-Renault-Dacia-Plugin).
