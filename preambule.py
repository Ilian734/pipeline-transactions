"""Preambule : prise en main de `sqlite3`.

Fichier a part, non note, mais qui etablit les points sur lesquels repose
tout le reste du projet. A lancer avec :

    python preambule.py

Chaque exercice affiche ce qu'il observe, puis la conclusion qu'on en tire.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

BASE = Path("essai.db")


def titre(numero: int, intitule: str) -> None:
    print(f"\n{'=' * 70}\n{numero}. {intitule}\n{'=' * 70}")


def exercice_1_connexions() -> None:
    titre(1, "Ouvrir, fermer, with, et :memory:")

    connexion = sqlite3.connect(BASE)
    connexion.close()
    print("connexion explicite ouverte puis fermee")

    with sqlite3.connect(BASE) as connexion:
        connexion.execute("SELECT 1")
    print("apres le bloc with, la connexion est-elle fermee ? ", end="")
    try:
        connexion.execute("SELECT 1")
        print("NON")
    except sqlite3.ProgrammingError:
        print("oui")
    connexion.close()

    print(
        "\n  Piege : `with sqlite3.connect(...)` ne ferme PAS la connexion.\n"
        "  Le gestionnaire de contexte gere la TRANSACTION (commit si le bloc\n"
        "  sort normalement, rollback s'il leve). Pour fermer il faut soit un\n"
        "  .close() explicite, soit contextlib.closing(...)."
    )

    memoire = sqlite3.connect(":memory:")
    memoire.execute("CREATE TABLE t (x INTEGER)")
    memoire.execute("INSERT INTO t VALUES (1)")
    memoire.commit()
    memoire.close()
    verification = sqlite3.connect(":memory:")
    tables = verification.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()
    verification.close()
    print(f"\n  Apres close(), une base :memory: contient : {tables} (vide)")
    print(
        "  Une base :memory: vit dans le processus : tout disparait a la\n"
        "  fermeture. Parfait pour les tests (rapide, isole), inutilisable\n"
        "  pour persister."
    )


def exercice_2_create_table() -> None:
    titre(2, "Creer la table clients deux fois de suite")

    with sqlite3.connect(":memory:") as connexion:
        connexion.execute(
            "CREATE TABLE clients ("
            " id INTEGER PRIMARY KEY AUTOINCREMENT,"
            " nom TEXT NOT NULL,"
            " pays TEXT NOT NULL)"
        )
        try:
            connexion.execute(
                "CREATE TABLE clients ("
                " id INTEGER PRIMARY KEY AUTOINCREMENT,"
                " nom TEXT NOT NULL,"
                " pays TEXT NOT NULL)"
            )
        except sqlite3.OperationalError as erreur:
            print(f"  2e CREATE TABLE -> {type(erreur).__name__}: {erreur}")

        connexion.execute("CREATE TABLE IF NOT EXISTS clients (id INTEGER)")
        print("  avec IF NOT EXISTS -> aucune erreur, le script est rejouable")
    connexion.close()


def exercice_3_insertions_et_commit() -> None:
    titre(3, "execute, executemany, et l'oubli du commit")

    if BASE.exists():
        BASE.unlink()

    connexion = sqlite3.connect(BASE)
    connexion.execute(
        "CREATE TABLE clients ("
        " id INTEGER PRIMARY KEY AUTOINCREMENT, nom TEXT, pays TEXT)"
    )
    for nom, pays in [("Alice", "FR"), ("Bob", "DE"), ("Chloe", "FR")]:
        connexion.execute("INSERT INTO clients (nom, pays) VALUES (?, ?)", (nom, pays))
    connexion.executemany(
        "INSERT INTO clients (nom, pays) VALUES (?, ?)",
        [("Dimitri", "ES"), ("Elena", "IT"), ("Farid", "FR")],
    )
    connexion.commit()
    connexion.close()

    connexion = sqlite3.connect(BASE)
    total = connexion.execute("SELECT COUNT(*) FROM clients").fetchone()[0]
    print(f"  apres commit + reouverture : {total} clients")

    connexion.execute("INSERT INTO clients (nom, pays) VALUES ('Fantome', 'XX')")
    connexion.close()

    connexion = sqlite3.connect(BASE)
    total = connexion.execute("SELECT COUNT(*) FROM clients").fetchone()[0]
    print(f"  apres une insertion SANS commit + reouverture : {total} clients")
    connexion.close()

    print(
        "\n  Sans commit, close() annule la transaction en cours : la ligne est\n"
        "  perdue, silencieusement. C'est exactement ce qui rend le couple\n"
        "  commit/rollback utilisable pour l'atomicite (etape 3)."
    )


def exercice_4_group_by_et_row_factory() -> None:
    titre(4, "Compter les clients par pays, puis row_factory")

    connexion = sqlite3.connect(BASE)
    requete = "SELECT pays, COUNT(*) AS nb FROM clients GROUP BY pays ORDER BY pays"

    print("  acces par index :")
    for ligne in connexion.execute(requete):
        print(f"    {ligne[0]} -> {ligne[1]}")

    connexion.row_factory = sqlite3.Row
    print("  acces par nom de colonne (row_factory = sqlite3.Row) :")
    for ligne_nommee in connexion.execute(requete):
        print(f"    {ligne_nommee['pays']} -> {ligne_nommee['nb']}")

    connexion.close()
    print(
        "\n  sqlite3.Row supprime les index magiques : si une colonne est\n"
        "  ajoutee a la requete, le code existant ne casse pas."
    )


def exercice_5_injection_sql() -> None:
    titre(5, "Parametre ? contre f-string : l'injection SQL")

    charge = "Robert'); DROP TABLE clients;--"

    connexion = sqlite3.connect(":memory:")
    connexion.execute("CREATE TABLE clients (id INTEGER PRIMARY KEY, nom TEXT)")
    connexion.execute("INSERT INTO clients (nom) VALUES (?)", (charge,))
    stocke = connexion.execute("SELECT nom FROM clients").fetchone()[0]
    print(f"  avec ? -> stocke tel quel : {stocke!r}")
    print("     la table clients existe toujours")

    try:
        connexion.execute(f"INSERT INTO clients (nom) VALUES ('{charge}')")
    except sqlite3.Warning as erreur:
        print(f"  avec f-string + execute -> {type(erreur).__name__}: {erreur}")
    except sqlite3.Error as erreur:
        print(f"  avec f-string + execute -> {type(erreur).__name__}: {erreur}")

    connexion.executescript(f"INSERT INTO clients (nom) VALUES ('{charge}')")
    tables = connexion.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()
    print(f"  avec f-string + executescript -> tables restantes : {tables}")
    connexion.close()

    print(
        "\n  `execute` refuse plusieurs instructions, ce qui limite les degats,\n"
        "  mais `executescript` les accepte et la table disparait. La regle ne\n"
        "  souffre aucune exception : les valeurs passent par ?, jamais par\n"
        "  interpolation de chaine. En prime, le driver gere l'echappement et\n"
        "  les types."
    )


def exercice_6_cles_etrangeres() -> None:
    titre(6, "Cle etrangere : pourquoi l'insertion orpheline passe")

    connexion = sqlite3.connect(":memory:")
    connexion.execute("CREATE TABLE clients (id INTEGER PRIMARY KEY, nom TEXT)")
    connexion.execute(
        "CREATE TABLE commandes ("
        " id INTEGER PRIMARY KEY,"
        " client_id INTEGER NOT NULL REFERENCES clients(id),"
        " montant REAL)"
    )

    actif = connexion.execute("PRAGMA foreign_keys").fetchone()[0]
    print(f"  PRAGMA foreign_keys par defaut = {actif}")
    connexion.execute("INSERT INTO commandes (client_id, montant) VALUES (999, 10.0)")
    print("  insertion vers le client inexistant 999 -> acceptee")

    connexion.execute("DELETE FROM commandes")
    connexion.execute("PRAGMA foreign_keys = ON")
    etat = connexion.execute("PRAGMA foreign_keys").fetchone()[0]
    print(f"  PRAGMA pose pendant une transaction implicite -> etat = {etat}")

    connexion.commit()
    connexion.execute("PRAGMA foreign_keys = ON")
    etat = connexion.execute("PRAGMA foreign_keys").fetchone()[0]
    print(f"  PRAGMA pose hors transaction -> etat = {etat}")

    try:
        connexion.execute(
            "INSERT INTO commandes (client_id, montant) VALUES (999, 10.0)"
        )
    except sqlite3.IntegrityError as erreur:
        print(f"  insertion orpheline -> {type(erreur).__name__}: {erreur}")
    connexion.close()

    print(
        "\n  Deux pieges cumules :\n"
        "  1. SQLite n'applique pas les cles etrangeres par defaut, pour rester\n"
        "     compatible avec les bases anterieures a leur introduction ;\n"
        "  2. `PRAGMA foreign_keys` est un no-op SILENCIEUX a l'interieur d'une\n"
        "     transaction. Le DELETE ci-dessus en avait ouvert une (comportement\n"
        "     par defaut de sqlite3), donc le premier PRAGMA n'a servi a rien et\n"
        "     n'a leve aucune erreur.\n"
        "  Le PRAGMA est par connexion et doit etre pose juste apres connect(),\n"
        "  hors transaction. C'est ce que fait `pipeline.persistance.connecter`."
    )


def exercice_7_transaction_et_rollback() -> None:
    titre(7, "Transaction : la premiere insertion part avec la seconde")

    connexion = sqlite3.connect(":memory:", isolation_level=None)
    connexion.execute("CREATE TABLE clients (id INTEGER PRIMARY KEY, nom TEXT UNIQUE)")
    connexion.execute("INSERT INTO clients (nom) VALUES ('Deja la')")

    connexion.execute("BEGIN")
    try:
        connexion.execute("INSERT INTO clients (nom) VALUES ('Valide')")
        connexion.execute("INSERT INTO clients (nom) VALUES ('Deja la')")
        connexion.execute("COMMIT")
    except sqlite3.IntegrityError as erreur:
        print(f"  2e insertion -> {type(erreur).__name__}: {erreur}")
        connexion.execute("ROLLBACK")
        print("  ROLLBACK execute")

    noms = [str(ligne[0]) for ligne in connexion.execute("SELECT nom FROM clients")]
    print(f"  contenu final : {noms}")
    print("  -> 'Valide' a disparu alors que son insertion avait reussi")
    connexion.close()

    print(
        "\n  Une transaction est un tout. C'est la propriete sur laquelle\n"
        "  l'etape 3 s'appuie : un fichier entier passe, ou rien ne passe."
    )


def exercice_8_contrainte_unique() -> None:
    titre(8, "Contrainte UNIQUE : type exact de l'exception")

    connexion = sqlite3.connect(":memory:")
    connexion.execute("CREATE TABLE clients (id INTEGER PRIMARY KEY, email TEXT UNIQUE)")
    connexion.execute("INSERT INTO clients (email) VALUES ('a@b.fr')")
    try:
        connexion.execute("INSERT INTO clients (email) VALUES ('a@b.fr')")
    except sqlite3.IntegrityError as erreur:
        print(f"  type exact : {type(erreur)}")
        print(f"  message    : {erreur}")
        print(f"  hierarchie : {[c.__name__ for c in type(erreur).__mro__[:5]]}")
    connexion.close()

    print(
        "\n  sqlite3.IntegrityError herite de DatabaseError, lui-meme de Error.\n"
        "  Cette exception est DETERMINISTE : la rejouer donnera le meme\n"
        "  resultat. C'est le fondement de la politique de retry (etape 7)."
    )


def main() -> None:
    exercice_1_connexions()
    exercice_2_create_table()
    exercice_3_insertions_et_commit()
    exercice_4_group_by_et_row_factory()
    exercice_5_injection_sql()
    exercice_6_cles_etrangeres()
    exercice_7_transaction_et_rollback()
    exercice_8_contrainte_unique()

    if BASE.exists():
        BASE.unlink()
    print(f"\n{BASE} supprime. Fin du preambule.")


if __name__ == "__main__":
    main()
