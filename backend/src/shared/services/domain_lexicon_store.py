from typing import Any, Dict

import sqlite3
from pathlib import Path


class DomainLexiconStore:
    def __init__(self, db_path: str, domain_lexicon_schema_path: str):
        self.db_path = Path(db_path)
        # Absolute or relative path to the SQL schema file for initializing the spell lexicon database
        self.domain_lexicon_schema_path = Path(domain_lexicon_schema_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)


    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row # Format each row as a dictionary with column names as keys for ease of access
        conn.execute("PRAGMA journal_mode=WAL;")  # Enable Write-Ahead Logging for better concurrency
        conn.execute("PRAGMA synchronous=NORMAL;")  # Set synchronous to NORMAL for better performance with WAL
        return conn
    

    def init_db(self):
        with self._connect() as conn, open(self.domain_lexicon_schema_path, encoding='utf-8') as f:
            conn.executescript(f.read())
        
    
    def upsert_document_terms(self, doc_id: str, terms: Dict[str, int]) -> Dict[str, Any]:
        """
        Upsert document terms into the database.
        Used during ingestion of new documents or updates to existing documents in the knowledge base.

        Main idea:

            1. For the given doc_id, retrieve all existing terms and their term frequencies from doc_term_stats.

            2. For each existing term update its overall collection-level stats (collection_term_stats) by: 
                a. subtracting its term frequency in the document (doc_tf in doc_term_stats) 
                    from the collection-level term frequency (collection_tf)
                b. decrementing the document frequency of the term (doc_freq in collection_term_stats) by 1

            3. Remove all existing terms for the given doc_id from doc_term_stats

            4. Log number of new terms added to collection 

            5. For each term in the input terms dictionary, upsert the term frequency for
                the term in doc_term_stats for the given doc_id and update collection-level stats by:
                a. adding doc_id, term, and term frequency (doc_tf) as a new row into doc_term_stats
                b. incrementing the collection-level term frequency (collection_tf) with the document term frequency (doc_tf) 
                c. incrementing the document frequency of term (doc_freq in collection_term_stats) by 1 
            
            6. Clean up empty terms in collection_term_stats (collection_tf <= 0 or doc_freq <= 0)
        
        Input shape:
        - doc_id: str
            - e.g. "raw/a.pdf", "raw/b.pdf", etc.

        - terms: Dict[str, int]
            - e.g. {
                    "term1": 3,  # term1 appears 3 times in the document identified by doc_id
                    "term2": 5,  # term2 appears 5 times in the document identified by doc_id
                    ...
                }
        """
        with self._connect() as conn:

            cur = conn.cursor()
            
            # 1. Get all existing terms for given doc_id
            cur.execute("SELECT term, doc_tf FROM doc_term_stats WHERE doc_id = ?", (doc_id,))
            existing_rows = cur.fetchall()
            
            # 2(a)(b). Update(subtract) collection-level term stats for each term in existing_rows
            for row in existing_rows:
                term = row["term"]
                existing_doc_tf = row["doc_tf"]

                # Subtract the existing term frequency of the term in the document from the collection-level term frequency
                cur.execute(
                    """
                    UPDATE collection_term_stats
                    SET collection_tf = collection_tf - ?,
                        doc_freq = doc_freq - 1
                    WHERE term = ?
                    """, 
                    (existing_doc_tf, term)
                )

            # 3. Delete all existing terms for the given doc_id from doc_term_stats
            cur.execute("DELETE FROM doc_term_stats WHERE doc_id = ?", (doc_id,))

            # 4. Calculate number of new terms added for building final logs to be returned
            incoming_terms = [t for t, tf in terms.items() if tf > 0]

            if incoming_terms: # Non-empty list of incoming terms
                placeholders = ",".join("?" for _ in incoming_terms)
                cur.execute(
                    f"SELECT term FROM collection_term_stats WHERE term IN ({placeholders})",
                    incoming_terms,
                )
                existing = {row["term"] for row in cur.fetchall()}
                new_terms_added = len(set(incoming_terms) - existing)
            else:
                new_terms_added = 0

            # 5(a). Add new (doc_id, term, doc_tf) rows into doc_term_stats for each term in input terms
            for term, doc_tf in terms.items():
                if doc_tf <= 0:
                    continue

                cur.execute(
                    """
                    INSERT INTO doc_term_stats (doc_id, term, doc_tf)
                    VALUES (?, ?, ?)
                    """,
                    (doc_id, term, doc_tf)
                )

                # 5(b)(c). Update collection-level term stats
                cur.execute(
                    """
                    INSERT INTO collection_term_stats (term, collection_tf, doc_freq) 
                    VALUES (?, ?, ?)
                    ON CONFLICT(term)
                    DO UPDATE 
                    SET collection_tf = collection_tf + ?,
                        doc_freq = doc_freq + 1
                    """,
                    (term, doc_tf, 1, doc_tf)
                )

            # 6. Clean up empty terms in collection_term_stats
            cur.execute("DELETE FROM collection_term_stats WHERE collection_tf <= 0 OR doc_freq <= 0")
            conn.commit()


        summary = {
            "total_terms_processed": len(incoming_terms),
            "new_terms_added": new_terms_added
        }
        return summary


    def delete_document(self, doc_id: str) -> Dict[str, Any]:
        """
        Delete a document and its associated terms from the database.
        Used during deletion of documents from the knowledge base.

        Main idea:

            1. For the given doc_id, retrieve all existing terms and their term frequencies from doc_term_stats.

            2. For each existing term update its overall collection-level stats (collection_term_stats) by: 
                a. subtracting its term frequency in the document (doc_tf in doc_term_stats) 
                    from the collection-level term frequency (collection_tf)
                b. decrementing the document frequency of the term (doc_freq in collection_term_stats) by 1

            3. After collection-level stats for all existing terms in the given doc_id are updated, 
                remove all existing records (doc_id, term, doc_tf) for that doc_id from doc_term_stats

            5. Log number of existing terms to be dropped from collection_term_stats (collection_tf <= 0 or doc_freq <= 0)

            4. Execute transaction and clean up empty terms to be removed 
        
        """
        with self._connect() as conn:

            cur = conn.cursor()
            
            # 1. Get all existing terms for given doc_id
            cur.execute("SELECT term, doc_tf FROM doc_term_stats WHERE doc_id = ?", (doc_id,))
            existing_rows = cur.fetchall()
            num_terms_in_doc = len(existing_rows)

            # 2(a)(b). Update(subtract) collection level term stats for each term in existing_rows
            for row in existing_rows:
                term = row["term"]
                existing_doc_tf = row["doc_tf"]

                # Subtract the existing term frequency of the term in the document from the collection-level term frequency
                cur.execute(
                    """
                    UPDATE collection_term_stats
                    SET collection_tf = collection_tf - ?,
                        doc_freq = doc_freq - 1
                    WHERE term = ?
                    """, 
                    (existing_doc_tf, term)
                )
            
            # 3. Delete all existing terms for the given doc_id from doc_term_stats
            cur.execute("DELETE FROM doc_term_stats WHERE doc_id = ?", (doc_id,))

            # 4. Log number of terms to be dropped completely from collection
            cur.execute("SELECT term FROM collection_term_stats WHERE collection_tf <= 0 OR doc_freq <= 0"            )
            dropped_terms = [row["term"] for row in cur.fetchall()]
            existing_terms_dropped = len(dropped_terms)

            # 5. Execute removal of term to be dropped
            cur.execute("DELETE FROM collection_term_stats WHERE collection_tf <= 0 OR doc_freq <= 0")
            conn.commit()

        summary = {
            "total_terms_processed": num_terms_in_doc,
            "existing_terms_dropped": existing_terms_dropped
        }        
        return summary

    