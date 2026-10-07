# Pipeline de traitement de transactions financières

Mini-projet de remise à niveau Python : une pipeline locale qui génère des
fichiers CSV de transactions, les charge, les agrège, et les persiste dans une
base SQLite — le tout derrière une seule commande.

**Contraintes respectées** : SQLite via le module `sqlite3` de la stdlib, pas de
pandas, aucune dépendance d'exécution. `pytest` et `mypy` sont les seules
dépendances, et uniquement pour le développement.

| | |
|---|---|
| Tests | 91 tests, `pytest` vert |
| Typage | `mypy --strict` propre sur `src/` et `tests/` |
| Python | 3.12+ |

---

## Sommaire

- [Installation](#installation)
- [Commandes](#commandes)
- [Architecture](#architecture)
- [Schéma de la base](#schéma-de-la-base)
- [Stratégie de gestion des lignes invalides](#stratégie-de-gestion-des-lignes-invalides)
- [Mécanisme d'idempotence](#mécanisme-didempotence)
- [Étape 6 — comportement en cas d'échec](#étape-6--comportement-en-cas-déchec)
- [Étape 7 — politique de retry](#étape-7--politique-de-retry)
- [Préambule sqlite3](#préambule-sqlite3)
- [Bonus traités](#bonus-traités)

---

## Installation

Depuis un clone frais :

```bash
git clone <url-du-depot>
cd pipeline-transactions
python -m venv .venv
```

Activer l'environnement — Linux / macOS :

```bash
source .venv/bin/activate
```

Windows (PowerShell) :

```powershell
.venv\Scripts\Activate.ps1
```

Puis installer le projet et ses outils de développement :

```bash
python -m pip install -e ".[dev]"
```

---

## Commandes

Lancer la pipeline complète (génération des CSV, traitement, création de la
base, insertion) :

```bash
python -m pipeline
```

Lancer la pipeline et afficher les agrégats consolidés :

```bash
python -m pipeline --rapport
```

Lancer les tests :

```bash
python -m pytest
```

Vérifier le typage :

```bash
python -m mypy src/ tests/
```

Exécuter le préambule sqlite3 :

```bash
python preambule.py
```

### Options

| Option | Effet |
|---|---|
| `--donnees CHEMIN` | dossier des CSV (défaut `donnees`) |
| `--base CHEMIN` | fichier SQLite (défaut `transactions.db`) |
| `--sans-generation` | ne pas regénérer les CSV, traiter ceux déjà présents |
| `--injecter-erreur` | ajouter un CSV invalide (démonstration de l'étape 6) |
| `--rapport` | afficher les agrégats consolidés à la fin |
| `--verbeux` | journal en niveau `DEBUG` |

Le script sort avec le code **0** si tout est passé, **1** dès qu'un fichier a
échoué.

### Sortie attendue

```
$ python -m pipeline --rapport
INFO     pipeline: fichiers generes dans donnees
INFO     pipeline: transactions_2024-03-01.csv insere (id=1)
INFO     pipeline: transactions_2024-03-02.csv insere (id=2)
INFO     pipeline: transactions_2024-03-03.csv insere (id=3)
fichiers inseres : 3 | deja traites : 0 | en echec : 0
transactions en base       : 18
transactions > 5000 : 5

--- envoye_par_iban (consolide) ---
  DE89370400440532013000                5200.00 EUR
  ES9121000418450200051332               780.00 EUR
  FR7630003000507654321098765          18822.15 EUR
  FR7630006000011234567890189          40580.73 EUR
  IT60X0542811101000000123456            640.40 EUR
...
```

---

## Architecture

```
src/pipeline/
├── modeles.py       types du domaine : Transaction (TypedDict), CleAgregat, Agregats
├── montants.py      conversion Decimal <-> centimes
├── erreurs.py       LigneInvalideError, FichierInvalideError
├── generation.py    étape 1 — écriture des CSV (données en dur, reproductibles)
├── chargement.py    lecture + validation des CSV (seul module qui lit le disque)
├── traitement.py    étape 2 — agrégations, fonctions PURES
├── persistance.py   étape 3 — schéma, insertion atomique, idempotence, retry
└── cli.py           étape 4 — orchestration et ligne de commande

tests/
├── fabriques.py         construction de données en mémoire
├── test_montants.py     conversion Decimal/centimes
├── test_traitement.py   étape 2 — unitaires purs, ne lisent aucun fichier
├── test_chargement.py   validation et rejet global
├── test_persistance.py  atomicité, idempotence, clés étrangères
├── test_integration.py  étape 5 — bout en bout
├── test_echec.py        étape 6 — code de retour et base propre
└── test_retry.py        étape 7 — politique de retry
```

### Séparation chargement / traitement

Les fonctions de `traitement.py` sont **pures** : elles ne lisent aucun fichier,
n'impriment rien, et ne modifient pas leurs arguments. Elles prennent une
`Sequence[Transaction]` et renvoient de nouvelles structures. Un test
(`test_les_fonctions_de_traitement_sont_pures`) vérifie explicitement que les
arguments ressortent inchangés.

Conséquence : **aucun test unitaire de traitement ne touche le disque**. Les
données d'entrée sont construites directement dans le test via
`tests/fabriques.py`.

### Typage des montants

`float` est volontairement absent du projet. Un montant est un `Decimal` en
mémoire, un `int` de centimes en base. Les agrégats sont typés
`dict[CleAgregat, Decimal]`.

`CleAgregat` est un `NamedTuple` `(valeur, devise)` : la devise fait partie de
la clé d'agrégation, donc **additionner des EUR et des USD dans un même total
est structurellement impossible** — même si le jeu de données généré est
mono-devise. C'est le bonus multi-devises, traité par le typage plutôt que par
une vérification à l'exécution.

SQLite n'a pas de type décimal : stocker un montant en `REAL` réintroduirait
exactement l'imprécision que `Decimal` élimine. Les montants sont donc persistés
en centimes (`INTEGER`) et reconvertis à la lecture. `vers_centimes` refuse tout
montant à plus de deux décimales plutôt que d'arrondir en silence.

---

## Schéma de la base

```sql
CREATE TABLE fichiers (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    nom             TEXT    NOT NULL,
    empreinte       TEXT    NOT NULL UNIQUE,   -- SHA-256 du contenu
    date_traitement TEXT    NOT NULL,
    nb_transactions INTEGER NOT NULL CHECK (nb_transactions > 0)
);

CREATE TABLE transactions (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    fichier_id           INTEGER NOT NULL REFERENCES fichiers(id) ON DELETE CASCADE,
    datetime_transaction TEXT    NOT NULL,
    iban_origine         TEXT    NOT NULL,
    pays_source          TEXT    NOT NULL,
    banque_source        TEXT    NOT NULL,
    iban_destinataire    TEXT    NOT NULL,
    pays_destinataire    TEXT    NOT NULL,
    montant_centimes     INTEGER NOT NULL CHECK (montant_centimes > 0),
    devise               TEXT    NOT NULL,
    au_dessus_du_seuil   INTEGER NOT NULL CHECK (au_dessus_du_seuil IN (0, 1))
);

CREATE TABLE agregats (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    fichier_id     INTEGER NOT NULL REFERENCES fichiers(id) ON DELETE CASCADE,
    type_agregat   TEXT    NOT NULL
        CHECK (type_agregat IN ('envoye_par_iban', 'envoye_par_banque', 'recu_par_iban')),
    cle            TEXT    NOT NULL,
    devise         TEXT    NOT NULL,
    total_centimes INTEGER NOT NULL,
    UNIQUE (fichier_id, type_agregat, cle, devise)
);
```

Choix notables :

- **`empreinte` est `UNIQUE`** : c'est le pivot de l'idempotence (voir plus bas).
- **`montant_centimes INTEGER`** et non `REAL` : exactitude des sommes.
- **`au_dessus_du_seuil`** est stocké, donc le drapeau calculé à l'étape 2 est
  persisté avec la transaction plutôt que recalculé à chaque lecture.
- **`ON DELETE CASCADE`** : supprimer un fichier retire ses transactions et ses
  agrégats, sans ligne orpheline.
- **`PRAGMA foreign_keys = ON`** est posé dans `connecter()`, juste après
  `connect()` et hors transaction. SQLite n'applique pas les clés étrangères par
  défaut, et le PRAGMA est un *no-op silencieux* si on le pose à l'intérieur
  d'une transaction — les deux pièges sont démontrés dans `preambule.py`.
- Les agrégats sont stockés **par fichier**. Les agrégats tous fichiers
  confondus sont recalculés en SQL (`SUM ... GROUP BY`) par
  `agregats_consolides()`, ce qui évite de maintenir deux sources de vérité.

---

## Stratégie de gestion des lignes invalides

**Rejet global : une seule ligne invalide fait échouer tout le fichier.**

Est considérée invalide une ligne dont : le montant n'est pas numérique, est
négatif, nul, non fini, ou a plus de deux décimales ; une colonne obligatoire
est absente ou vide ; la date n'est pas lisible en ISO 8601 ; l'IBAN, le code
pays ou le code devise est mal formé ; l'IBAN d'origine est égal à celui du
destinataire.

### Pourquoi ce choix

Le domaine est financier. Une ligne illisible dans un lot de transactions
signale presque toujours un problème *en amont* — mauvais export, encodage
cassé, format changé sans prévenir. Dans ce contexte, charger les 17 lignes
« correctes » et jeter la 18e produit des agrégats qui ont l'air valides mais
qui sont faux, et le rapprochement comptable ne tombera jamais juste. Mieux vaut
un fichier manquant et bruyant qu'un total silencieusement incomplet.

Ce choix rend aussi la cohérence avec l'étape 6 immédiate : « pas d'insertion
partielle du fichier en échec » découle directement de la stratégie, au lieu
d'être une règle supplémentaire à faire respecter.

### Conséquences, et comment elles sont tenues

- Le chargement échoue **avant** toute écriture en base : `charger_fichier()`
  lève `FichierInvalideError` et ne renvoie aucune transaction.
- Un fichier en échec **n'interrompt pas les autres**. Chaque fichier est une
  unité de travail indépendante ; les fichiers valides sont insérés normalement
  et le bilan final porte le code de retour.
- Le message d'erreur donne le numéro de ligne **tel qu'il apparaît dans le
  fichier**, en-tête comprise (la première transaction est donc la ligne 2).

Tests correspondants : `test_rejet_global_une_ligne_invalide_fait_tomber_le_fichier`,
`test_la_base_reste_propre_apres_un_echec`,
`test_les_fichiers_valides_passent_malgre_l_echec`.

### Si l'autre stratégie était retenue

Isoler et compter les lignes invalides serait défendable dans un contexte
d'ingestion « best effort » (logs, télémétrie). Il faudrait alors une table de
rejets, un compteur par fichier, et un seuil au-delà duquel le fichier bascule
quand même en échec — sans quoi un fichier à 100 % invalide serait traité comme
un succès à 0 ligne.

---

## Mécanisme d'idempotence

**Un fichier est identifié par le SHA-256 de son contenu**, pas par son nom.

L'empreinte est calculée sur les octets bruts du fichier
(`chargement.empreinte_contenu`), stockée dans `fichiers.empreinte`, et cette
colonne porte une contrainte `UNIQUE`.

À chaque insertion, `inserer_fichier()` ouvre une transaction, vérifie si
l'empreinte est déjà connue, et renvoie `None` sans rien écrire si c'est le cas.

### Pourquoi le nom ne suffit pas

L'énoncé le souligne, et les deux cas sont couverts par des tests :

| Situation | Comportement | Test |
|---|---|---|
| Même contenu, même nom | traité une seule fois | `test_idempotence_meme_contenu` |
| Même contenu, nom différent | traité une seule fois | `test_idempotence_meme_contenu_nom_different` |
| Contenu différent, même nom | traité **deux fois** (ce sont deux lots) | `test_contenus_differents_meme_nom_sont_deux_fichiers` |

Le dernier cas est le plus important : un `transactions.csv` qui change tous les
jours doit être réingéré chaque jour. Filtrer sur le nom le rendrait invisible
après la première fois.

### Double verrou

La vérification Python (`fichier_deja_traite`) évite le travail inutile, et la
contrainte `UNIQUE` en base est le filet de sécurité : même si deux processus
vérifiaient simultanément, la base refuserait le doublon. Le `BEGIN IMMEDIATE`
pris en début d'insertion sérialise de toute façon les écrivains concurrents.

La génération est elle aussi **reproductible** — données en dur, aucun `random`,
`lineterminator="\n"` imposé à l'écriture des CSV pour que l'empreinte soit
identique sous Windows et sous Linux. Relancer `python -m pipeline` produit donc
exactement les mêmes octets, donc les mêmes empreintes, donc aucune réinsertion.

```
$ python -m pipeline     # 2e exécution
INFO     pipeline.persistance: fichier transactions_2024-03-01.csv deja traite (empreinte fc1b3ce0ba43), ignore
INFO     pipeline.persistance: fichier transactions_2024-03-02.csv deja traite (empreinte 8a7c75cb4609), ignore
INFO     pipeline.persistance: fichier transactions_2024-03-03.csv deja traite (empreinte 3d0ca8f30376), ignore
fichiers inseres : 0 | deja traites : 3 | en echec : 0
```

### Atomicité

L'insertion d'un fichier est atomique. `connecter()` ouvre la connexion avec
`isolation_level=None`, ce qui désactive la gestion implicite des transactions
de `sqlite3` : les `BEGIN IMMEDIATE` / `COMMIT` / `ROLLBACK` sont écrits
explicitement. Fichier, transactions et agrégats entrent dans la même
transaction ; toute exception déclenche un `ROLLBACK`.

`test_insertion_atomique_rien_ne_reste_en_cas_d_echec` le vérifie en faisant
échouer l'insertion *après* que la ligne de `fichiers` a été écrite, et en
constatant qu'elle a disparu.

---

## Étape 6 — comportement en cas d'échec

### Provoquer l'échec

`--injecter-erreur` ajoute un quatrième CSV dont la 2ᵉ transaction porte le
montant `mille euros`. Ce fichier est conçu pour être piégeux : sa 1ʳᵉ ligne est
valide et sa 3ᵉ dépasse le seuil, donc un traitement partiel laisserait des
traces bien visibles en base.

### Sortie réelle de la pipeline

```
$ python -m pipeline --injecter-erreur ; echo "code de retour: $?"
INFO     pipeline: fichiers generes dans donnees
INFO     pipeline: transactions_2024-03-01.csv insere (id=1)
INFO     pipeline: transactions_2024-03-02.csv insere (id=2)
INFO     pipeline: transactions_2024-03-03.csv insere (id=3)
ERROR    pipeline: echec sur transactions_2024-03-04_corrompu.csv : fichier transactions_2024-03-04_corrompu.csv rejete : ligne 3 : montant non numerique : 'mille euros'
ECHEC transactions_2024-03-04_corrompu.csv : fichier transactions_2024-03-04_corrompu.csv rejete : ligne 3 : montant non numerique : 'mille euros'
fichiers inseres : 3 | deja traites : 0 | en echec : 1
code de retour: 1
```

État de la base après cet échec : **18 transactions, 3 fichiers**. Aucune des
deux lignes valides du fichier corrompu n'est présente. Les tests de
`tests/test_echec.py` assertent le code de retour (y compris celui du vrai
processus, lancé en `subprocess`), le nombre de lignes, l'absence du fichier
corrompu dans `fichiers`, et l'absence de ses montants dans `transactions`.

### Une erreur vue par mypy mais pas par les tests

Modification introduite dans `afficher_rapport()` (`src/pipeline/cli.py`) — une
mise à l'échelle qui mélange `Decimal` et `float` :

```python
print(f"  {cle.valeur:<32} {total * 1.2:>12} {cle.devise}")
```

**pytest :**

```
91 passed in 3.52s
```

**mypy :**

```
src\pipeline\cli.py:129: error: Unsupported operand types for * ("Decimal" and "float")  [operator]
Found 1 error in 1 file (checked 18 source files)
```

À l'exécution, cette ligne lèverait :

```
TypeError: unsupported operand type(s) for *: 'decimal.Decimal' and 'float'
```

### Ce que cela apprend sur les deux outils

Les tests passent parce que **aucun test n'appelle `afficher_rapport()`** : cette
fonction n'est atteinte que via l'option `--rapport`. Un test ne peut rien dire
d'un chemin qu'il n'exécute pas. La suite était verte, le typage était faux, et
le bug n'aurait éclaté qu'en production, à la première personne qui passe
`--rapport`.

mypy, lui, ne raisonne pas sur des exécutions mais sur du texte : il voit
*toutes* les lignes, couvertes ou non, et vérifie que les types sont cohérents
partout. Il n'a besoin d'aucun jeu de données pour trouver l'erreur.

La symétrie est tout aussi vraie dans l'autre sens, et c'est pour cela qu'aucun
des deux ne remplace l'autre : si je remplace `>` par `>=` dans
`est_au_dessus_du_seuil`, mypy reste parfaitement muet — les deux opérateurs
sont bien typés, `bool` est bien renvoyé. Seul
`test_seuil_est_une_comparaison_stricte`, qui connaît la *règle métier*
(5000.00 n'est pas « au-dessus de 5000 »), attrape la faute.

En résumé : **mypy couvre tout le code mais ignore l'intention ; les tests
connaissent l'intention mais ne couvrent que ce qu'ils exécutent.** Le typage
coûte presque rien à faire tourner et élimine toute une classe d'erreurs
mécaniques ; les tests restent indispensables pour tout ce qui relève de la
logique métier. Les deux tournent dans la CI, à chaque push.

---

## Étape 7 — politique de retry

### Quelles erreurs justifient un retry ?

La question n'est pas « cette erreur est-elle grave ? » mais **« l'état du monde
peut-il changer tout seul d'ici la prochaine tentative ? »**. Cela partage les
exceptions `sqlite3` en deux familles.

#### Retryables — contention transitoire

`sqlite3.OperationalError` dont le message contient `database is locked` ou
`database is busy`.

Ces erreurs ne disent rien sur la requête : elles disent qu'une **autre**
connexion détenait le verrou à cet instant. SQLite n'autorise qu'un seul
écrivain à la fois. La requête est correcte, les données sont correctes, c'est
le calendrier qui ne l'était pas. Dès que l'autre transaction rend le verrou, la
même requête réussit à l'identique. C'est exactement le cas qu'un retry avec
backoff est fait pour absorber.

#### Non retryables — erreurs déterministes

- `sqlite3.IntegrityError` — contrainte violée : `UNIQUE`, `FOREIGN KEY`,
  `CHECK`, `NOT NULL`. La donnée *elle-même* est en conflit avec le schéma.
  Rejouer la même requête sur le même état donnera exactement la même erreur.
- `sqlite3.ProgrammingError` — mauvais nombre de paramètres, connexion fermée,
  utilisation depuis un autre thread. C'est un bug dans le code appelant.
- `sqlite3.OperationalError` **de schéma** — `no such table`, `no such column`.
  Même classe d'exception que le verrou, mais rien de transitoire : la table
  n'apparaîtra pas spontanément.

Ce dernier point est la subtilité du sujet : **le type de l'exception ne suffit
pas à décider**. `OperationalError` recouvre à la fois le verrou (retryable) et
le schéma absent (jamais retryable). `est_erreur_retryable()` inspecte donc le
message, et un test paramétré fige la classification des neuf cas.

Rejouer une erreur déterministe est activement nuisible : cela transforme un
échec immédiat et lisible en une attente multipliée par le backoff, puis en la
même erreur — en ayant perdu du temps et brouillé les journaux.

### Implémentation

`persistance.executer_avec_retry()` : backoff exponentiel (0.1 s, 0.2 s,
0.4 s…), 3 tentatives par défaut. Une erreur non retryable est relancée
**immédiatement**, sans consommer d'essai ni dormir. La fonction `dormir` est
injectable, ce qui rend les tests instantanés et déterministes.

Le chargement du CSV est délibérément **hors** du retry (`cli.traiter_fichier`) :
une erreur de parsing est déterministe par nature, la rejouer ne changerait rien.
Seule l'insertion est rejouable.

### Tests

- `test_classification_des_erreurs` — 9 cas paramétrés, verrou contre schéma
  contre intégrité ;
- `test_erreur_transitoire_rejouee_jusqu_au_succes` — échoue 2 fois, réussit au
  3ᵉ essai ;
- `test_erreur_deterministe_jamais_rejouee` — une `IntegrityError` n'est appelée
  **qu'une seule fois** ;
- `test_backoff_exponentiel` — les délais valent bien `[0.1, 0.2, 0.4]` ;
- `test_la_reinsertion_aboutit_apres_une_erreur_retryable` — simule le verrou,
  puis vérifie que les données sont bien en base ;
- `test_verrou_reel_libere_pendant_le_retry` — cas concret : une autre connexion
  prend un `BEGIN EXCLUSIVE`, un thread écrivain part en retry, le verrou est
  relâché, l'insertion aboutit. Chaque thread ouvre sa propre connexion, SQLite
  interdisant de partager un objet connexion entre threads.

### Remarque

Comme le note l'énoncé, en SQLite local les occasions de retry légitime sont
rares : un seul processus écrit, le verrou n'est presque jamais contesté. Le
mécanisme prend tout son sens dès qu'il y a plusieurs écrivains — d'où le test
avec verrou réel, qui est le seul à reproduire la situation pour de vrai.

---

## Préambule sqlite3

`preambule.py` répond aux 8 exercices, en affichant à chaque fois l'observation
réelle puis la conclusion. Les points qui ont directement façonné le code :

1. **`with sqlite3.connect(...)` ne ferme pas la connexion** — il gère la
   *transaction* (commit en sortie normale, rollback sur exception). Pour fermer,
   il faut `.close()` ou `contextlib.closing`.
2. **`CREATE TABLE` deux fois** → `OperationalError: table clients already
   exists` ; `IF NOT EXISTS` rend le script rejouable, ce qui est la base de
   `creer_schema()`.
3. **Sans `commit`, `close()` annule la transaction** — la ligne est perdue
   silencieusement. C'est cette propriété qui rend `commit`/`rollback`
   utilisable pour l'atomicité.
4. **`row_factory = sqlite3.Row`** supprime les index magiques : ajouter une
   colonne à une requête ne casse plus le code existant.
5. **Injection SQL** — avec `?`, la charge `Robert'); DROP TABLE clients;--` est
   stockée telle quelle, comme un simple nom. Avec une f-string, `execute` lève
   `ProgrammingError: You can only execute one statement at a time` — mais
   `executescript` accepte l'enchaînement et **la table disparaît pour de bon**
   (`tables restantes : []`). Les valeurs passent par `?`, sans exception.
6. **Clés étrangères** — l'insertion orpheline passe parce que
   `PRAGMA foreign_keys` vaut `0` par défaut (compatibilité avec les bases
   antérieures à leur introduction). Piège supplémentaire découvert ici : le
   PRAGMA est un **no-op silencieux à l'intérieur d'une transaction**. Posé après
   un `DELETE` (qui en a ouvert une implicitement), il ne fait rien et ne lève
   rien. Il doit être posé juste après `connect()`, hors transaction — c'est ce
   que fait `connecter()`.
7. **Transaction et rollback** — une insertion réussie disparaît avec le
   `ROLLBACK` déclenché par la suivante. Une transaction est un tout.
8. **Contrainte `UNIQUE`** → `sqlite3.IntegrityError`, qui hérite de
   `DatabaseError` puis de `Error`. Son caractère **déterministe** est le
   fondement de la politique de retry de l'étape 7.

---

## Bonus traités

- **CI GitHub Actions** (`.github/workflows/ci.yml`) — `mypy`, `pytest`, le
  préambule, la pipeline de bout en bout, un contrôle d'idempotence et un
  contrôle du code de retour non nul, sur Python 3.12 et 3.13, à chaque push.
- **Multi-devises** — les agrégats sont indexés par `(valeur, devise)` via
  `CleAgregat`. Mélanger deux devises dans un total est impossible par
  construction, et `test_les_devises_ne_sont_jamais_melangees` le verrouille.
- **Agrégats consolidés tous fichiers confondus** — `agregats_consolides()`
  (`SUM ... GROUP BY` en SQL), affichés par `--rapport`.
- **Logging** — module `logging` de la stdlib, journal sur `stderr` pour laisser
  `stdout` propre, niveau `DEBUG` via `--verbeux`.
- **Validation des données en entrée** — montants, dates ISO, format des IBAN,
  codes pays et devises, cohérence origine ≠ destinataire.
- **Configuration `ruff`** — présente dans `pyproject.toml` (`ruff` n'est pas
  une dépendance autorisée, la configuration est fournie pour qui veut la
  lancer).

### Non traités

- **PostgreSQL** — le sujet impose SQLite, et c'est aussi là que la question du
  retry deviendrait vraiment concrète.
- **S3 / MinIO** — demanderait `boto3`, hors des dépendances autorisées.
