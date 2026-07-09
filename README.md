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
| Lancement de charge | ✅ | ✅ |
| **Arrêt de charge** | ❌ `Endpoint 'actions/charge-stop' not available for model 'R5E1VE'` | ✅ *(via bascule KCM, à valider en réel)* |
| **Recharge programmée** | ❌ (l'arrêt planifié plantait) | ✅ *(dépend de l'arrêt de charge)* |
| Intervalle mini de polling | 10 min | **5 min** |

### Pourquoi l'arrêt de charge plantait, et comment c'est réparé

La R5 est un véhicule de génération **KCM**. Dans la bibliothèque `renault-api`, le modèle `R5E1VE` déclare explicitement l'action d'arrêt comme indisponible :

```python
"R5E1VE": {  # Renault 5 E-TECH
    "actions/charge-start": .../ev/settings (mode kcm-settings),
    "actions/charge-stop": None,  # Not supported - use charger to stop
    ...
}
```

Résultat : l'appel `vehicle.set_charge_stop()` lève `EndpointNotAvailableError` **avant même d'envoyer une requête**, d'où l'erreur mentionnant `R5E1VE`. Comme la « recharge programmée » du plugin met simplement en file un ordre d'arrêt (via dzVents) en fin de créneau, elle échouait pour la même raison.

**Correctif** : la méthode `stopCharge()` du plugin essaie d'abord `set_charge_stop()` (comportement normal, conservé pour Zoé, Spring, etc.). Si `EndpointNotAvailableError` est levée, elle bascule automatiquement sur l'endpoint KCM `charge/pause-resume` en envoyant directement, via `vehicle.http_post()`, la charge utile documentée :

```
POST /commerce/v1/accounts/{account_id}/kamereon/kcm/v1/vehicles/{vin}/charge/pause-resume
{ "data": { "type": "ChargePauseResume", "attributes": { "action": "pause" } } }
```

Cette bascule est **générique** : tout véhicule KCM dont `actions/charge-stop` est `None` en bénéficie (utile pour la future compatibilité R4 / Twingo, sans code spécifique par modèle).

**Pourquoi ce choix est solide (et pas un bricolage) :** le pause-resume KCM est *déjà* le mécanisme d'arrêt utilisé nativement par `renault-api` pour d'autres véhicules KCM — la **Zoe phase 2** (`X102VE`) et la **Dacia Spring** (`XBG1VE`) mappent toutes deux `actions/charge-stop` vers `charge-stop-via-pause-resume`. Ce fork applique donc simplement le même mécanisme à la R5. De plus, dans `renault-api`, la ligne `actions/charge-stop: None` de la R5 est la **seule** de son bloc sans code d'erreur Renault à l'appui (les autres indisponibilités citent `err.func.wired.forbidden`, `not-found`, etc.) : la mention « use charger to stop » ressemble à une conclusion prudente du contributeur plutôt qu'à un refus API réellement constaté sur l'endpoint pause-resume.

> ℹ️ Le payload historique `{"action":"stop"}` visible dans la doc sur `actions/charging-start` concerne l'ancien endpoint **KCA** (`kca/car-adapter/...`) ; il **ne s'applique pas** à la R5, qui est KCM. Utiliser la High-level API (`set_charge_stop()`) ne suffit pas non plus : elle échoue *avant* tout appel réseau car le mapping du modèle vaut `None`. Le `http_post()` direct vers l'endpoint KCM est donc le bon contournement.

> ⚠️ **À confirmer sur le terrain.** L'action `pause` reste à valider sur la R5 précise : selon l'abonnement (« Pack EV Remote Control ») et le firmware, l'API peut répondre `err.func.wired.forbidden`. Le plugin journalise désormais la **réponse de l'API** (ou l'erreur exacte) après un arrêt, pour faciliter le diagnostic. **Le lancement de charge**, lui, fonctionne nativement (mode `kcm-settings` : il désactive les programmes planifiés pour déclencher une charge immédiate).

### Comment tester l'arrêt de charge

1. Assurez-vous que le véhicule est **branché et en charge** (le dispositif *Branchée* = 1, *Charge en cours* = 1).
2. Dans Domoticz, activez les logs (Configuration → Paramètres → onglet *Autres* → journalisation) ou surveillez le journal du plugin.
3. Appuyez sur le dispositif **Arrêter la charge**.
4. Dans les logs Domoticz, vous devriez voir l'une de ces situations :
   - `Charge arrêtée pour <nom> (set_charge_stop).` → la voie standard a fonctionné.
   - `'set_charge_stop' indisponible pour ce modèle (...). Bascule sur l'endpoint KCM 'charge/pause-resume' (action pause)...` suivi de `Commande 'pause' envoyée pour <nom> (KCM charge/pause-resume).` → la bascule KCM a été acceptée. **Vérifiez physiquement que la charge s'est bien arrêtée.**
   - Une erreur `err.func.wired.forbidden` / `err.func.wired.overloaded` → voir ci-dessous.

En complément, vous pouvez tester la commande brute hors Domoticz avec la CLI `renault-api` :

```
renault-api --account <ACCOUNT_ID> --vin <VIN> http post \
  "/commerce/v1/accounts/{account_id}/kamereon/kcm/v1/vehicles/{vin}/charge/pause-resume" \
  '{"data":{"type":"ChargePauseResume","attributes":{"action":"pause"}}}'
```

(et `"action":"resume"` pour relancer). Cela permet d'isoler un éventuel problème d'abonnement/permissions Renault d'un problème de plugin.

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

- L'arrêt de charge R5 via `pause-resume` reste **à confirmer** sur le terrain (voir avertissement plus haut).
- La « recharge programmée » du plugin est gérée **côté Domoticz** (dzVents planifie un ON puis un OFF), et non via l'API de planification native Renault. Elle dépend donc du bon fonctionnement des ordres de lancement/arrêt.
- R4 E-Tech et Twingo ne sont **pas encore testées** ; la bascule KCM générique devrait toutefois s'appliquer si leur `actions/charge-stop` est aussi `None`.

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

### v1.0.2 (fork lemassykoi)
- **Compatibilité Renault 5 E-Tech (`R5E1VE`)** : l'arrêt de charge bascule automatiquement sur l'endpoint KCM `charge/pause-resume` (action `pause`) quand `set_charge_stop()` n'est pas disponible pour le modèle (`EndpointNotAvailableError`). Correction indirecte de la « recharge programmée » qui dépend de l'arrêt de charge. *(À valider en conditions réelles.)*
- Bascule **générique** : profite aussi aux futurs modèles KCM (R4 E-Tech, Twingo…) sans code spécifique.
- Ajout de l'option de fréquence d'actualisation **5 minutes** (minimum précédent : 10 min).
- Documentation : quota API (~60 req/h), guide de test de l'arrêt de charge, limites connues.
- Mise à jour des liens (wiki/clone) vers le fork.

### v1.0.1 et antérieures
Voir le dépôt d'origine [Kask29/Domoticz-Renault-Dacia-Plugin](https://github.com/Kask29/Domoticz-Renault-Dacia-Plugin).
