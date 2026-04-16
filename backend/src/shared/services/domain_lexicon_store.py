from typing import Any, Dict, List, Set, Tuple
from nltk.util import ngrams
from botocore.exceptions import ClientError
from ..clients.dynamodb_client import DyanmoDBClient


class DomainLexiconStore:
    def __init__(self, collection_term_stats_table_name: str, doc_term_stats_table_name: str):
        if not collection_term_stats_table_name or not str(collection_term_stats_table_name).strip():
            raise ValueError("collection_term_stats_table_name is required")
        if not doc_term_stats_table_name or not str(doc_term_stats_table_name).strip():
            raise ValueError("doc_term_stats_table_name is required")

        self.collection_term_stats_table_name = collection_term_stats_table_name
        self.doc_term_stats_table_name = doc_term_stats_table_name
        self.dynamodb = DyanmoDBClient(collection_term_stats_table_name)

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

            4. Prepare incoming terms with positive tf for processing

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
        # 1. Get all existing terms for given doc_id
        existing_rows = self._query_doc_term_rows(doc_id=doc_id)
        old_terms = {term for term, _ in existing_rows}

        # 2(a)(b). Update(subtract) collection-level term stats for each term in existing_rows
        for term, existing_doc_tf in existing_rows:
            self._subtract_collection_term_stats_if_exists(term=term, doc_tf=existing_doc_tf)

        # 3. Delete all existing terms for the given doc_id from doc_term_stats
        self._delete_doc_term_rows(doc_id=doc_id, existing_rows=existing_rows)

        # 4. Prepare incoming terms for processing
        incoming_terms = [term for term, tf in terms.items() if tf > 0]
        incoming_terms_set = set(incoming_terms)

        # 5(a). Add new (doc_id, term, doc_tf) rows into doc_term_stats for each term in input terms
        for term, doc_tf in terms.items():
            if doc_tf <= 0:
                continue
            prefix1, prefix2, bigrams = self._build_term_features(term)
            self.dynamodb.client.put_item(
                TableName=self.doc_term_stats_table_name,
                Item={
                    "doc_id": {"S": doc_id},
                    "term": {"S": term},
                    "doc_tf": {"N": str(int(doc_tf))},
                },
            )

            # 5(b)(c). Update collection-level term stats
            self.dynamodb.client.update_item(
                TableName=self.collection_term_stats_table_name,
                Key={"term": {"S": term}},
                UpdateExpression=(
                    "SET prefix1 = if_not_exists(prefix1, :prefix1), "
                    "prefix2 = if_not_exists(prefix2, :prefix2), "
                    "bigrams = if_not_exists(bigrams, :bigrams), "
                    "collection_tf = if_not_exists(collection_tf, :zero) + :doc_tf, "
                    "doc_freq = if_not_exists(doc_freq, :zero) + :one"
                ),
                ExpressionAttributeValues={
                    ":prefix1": {"S": prefix1},
                    ":prefix2": {"S": prefix2} if prefix2 is not None else {"NULL": True},
                    ":bigrams": {"L": [{"S": bigram} for bigram in bigrams]},
                    ":zero": {"N": "0"},
                    ":doc_tf": {"N": str(int(doc_tf))},
                    ":one": {"N": "1"},
                },
            )

        # 6. Clean up empty terms in collection_term_stats (touched terms only)
        touched_terms = old_terms | incoming_terms_set
        dropped_terms = self._get_collection_terms_to_drop(touched_terms)
        self._delete_collection_terms(dropped_terms)

        summary = {
            "total_terms_processed": len(incoming_terms),
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

            4. Identify touched terms that should be dropped (`collection_tf <= 0` or `doc_freq <= 0`)

            5. Execute cleanup by deleting dropped collection terms
        """
        # 1. Get all existing terms for given doc_id
        existing_rows = self._query_doc_term_rows(doc_id=doc_id)
        num_terms_in_doc = len(existing_rows)

        # 2(a)(b). Update(subtract) collection level term stats for each term in existing_rows
        for term, existing_doc_tf in existing_rows:
            self._subtract_collection_term_stats_if_exists(term=term, doc_tf=existing_doc_tf)

        # 3. Delete all existing terms for the given doc_id from doc_term_stats
        self._delete_doc_term_rows(doc_id=doc_id, existing_rows=existing_rows)

        # 4. Identify terms to be dropped completely from collection
        dropped_terms = self._get_collection_terms_to_drop({term for term, _ in existing_rows})

        # 5. Execute removal of term to be dropped
        self._delete_collection_terms(dropped_terms)

        summary = {
            "total_terms_processed": num_terms_in_doc,
        }        
        return summary


    def _build_term_features(self, term: str) -> Tuple[str, str | None, List[str]]:
        """Build deterministic per-term features used by retrieval spell-correction."""
        prefix1 = term[0]
        prefix2 = term[:2] if len(term) >= 2 else None
        bigrams = sorted({"".join(bigram) for bigram in ngrams(term, n=2)})
        return prefix1, prefix2, bigrams


    def _query_doc_term_rows(self, doc_id: str) -> List[Tuple[str, int]]:
        """
        Query all rows (row_doc_id, row_term, row_tf) for in doc-term stats table and where row_doc_id = doc_id
        
        Returns a list of tuples for all associated terms associated with the doc_id:
            - [(row_term_1, row_tf_1), (row_term_2, row_tf_2), ... , (row_term_n, row_tf_n)]
        """
        
        out: List[Tuple[str, int]] = []
        query_kwargs: Dict[str, Any] = {
            "TableName": self.doc_term_stats_table_name,
            "KeyConditionExpression": "doc_id = :doc_id",
            "ExpressionAttributeValues": {":doc_id": {"S": doc_id}},
        }
        while True:
            response = self.dynamodb.client.query(**query_kwargs)
            items = response.get("Items", [])
            for item in items:
                term_attr = item.get("term", {})
                tf_attr = item.get("doc_tf", {})
                term = term_attr.get("S", "")
                doc_tf = int(tf_attr.get("N", "0"))
                if term:
                    out.append((term, doc_tf))
            last_evaluated_key = response.get("LastEvaluatedKey")
            if not last_evaluated_key:
                break
            query_kwargs["ExclusiveStartKey"] = last_evaluated_key
        return out


    def _subtract_collection_term_stats_if_exists(self, term: str, doc_tf: int) -> None:
        """
        Subtract one document's term contribution from collection-term stats table when the term row exists.
            - collection_tf = collection_tf - doc_tf
            - doc_freq -= 1
        """
        try:
            self.dynamodb.client.update_item(
                TableName=self.collection_term_stats_table_name,
                Key={"term": {"S": term}},
                UpdateExpression="SET collection_tf = collection_tf - :doc_tf, doc_freq = doc_freq - :one",
                ExpressionAttributeValues={
                    ":doc_tf": {"N": str(int(doc_tf))},
                    ":one": {"N": "1"},
                },
                ConditionExpression="attribute_exists(term)",
            )
        except ClientError as e:
            if e.response.get("Error", {}).get("Code") != "ConditionalCheckFailedException":
                raise


    def _delete_doc_term_rows(self, doc_id: str, existing_rows: List[Tuple[str, int]]) -> None:
        """
        Given a doc_id and a list of associated (term, tf) tuples,
        for each term, delete all (doc_id, term, tf) rows in doc-term stats table in batched chunks 
        """
        if not existing_rows:
            return
        delete_requests = [
            {
                "DeleteRequest": {
                    "Key": {"doc_id": {"S": doc_id}, "term": {"S": term}}
                }
            }
            for term, _ in existing_rows
        ]
        for i in range(0, len(delete_requests), 25):
            batch = delete_requests[i : i + 25]
            request_items = {self.doc_term_stats_table_name: batch}
            while True:
                response = self.dynamodb.client.batch_write_item(RequestItems=request_items)
                unprocessed = response.get("UnprocessedItems", {})
                pending = unprocessed.get(self.doc_term_stats_table_name, [])
                if not pending:
                    break
                request_items = {self.doc_term_stats_table_name: pending}


    def _get_collection_terms_to_drop(self, candidate_terms: Set[str]) -> List[str]:
        """
        Helper function that takes in a set of candidate terms (terms associated with upserted/deleted doc_id) 
        and batch-gets a list of terms (terms_to_drop) in collection-term stats table where:
            - collection_tf <= 0 OR
            - doc_freq <= 0

        Returned list of terms to drop to be processed for deletion from collection-term stats by _delete_collection_terms.
        """
        if not candidate_terms:
            return []

        items: List[Dict[str, Dict[str, str]]] = []
        terms_list = list(candidate_terms)
        for i in range(0, len(terms_list), 100):
            chunk = terms_list[i : i + 100]
            request_items = {
                self.collection_term_stats_table_name: {
                    "Keys": [{"term": {"S": t}} for t in chunk],
                    "ProjectionExpression": "term, collection_tf, doc_freq",
                }
            }
            while True:
                response = self.dynamodb.client.batch_get_item(RequestItems=request_items)
                items.extend(response.get("Responses", {}).get(self.collection_term_stats_table_name, []))
                unprocessed = response.get("UnprocessedKeys", {})
                pending = unprocessed.get(self.collection_term_stats_table_name)
                if not pending:
                    break
                request_items = {self.collection_term_stats_table_name: pending}

        terms_to_drop: List[str] = []
        for item in items:
            term = item.get("term", {}).get("S")
            collection_tf = int(item.get("collection_tf", {}).get("N", "0"))
            doc_freq = int(item.get("doc_freq", {}).get("N", "0"))
            if term and (collection_tf <= 0 or doc_freq <= 0):
                terms_to_drop.append(term)

        return terms_to_drop


    def _delete_collection_terms(self, terms: List[str]) -> None:
        """Delete collection-term rows for the provided term list using batched writes."""
        if not terms:
            return
        delete_requests = [
            {"DeleteRequest": {"Key": {"term": {"S": term}}}}
            for term in terms
        ]
        for i in range(0, len(delete_requests), 25):
            batch = delete_requests[i : i + 25]
            request_items = {self.collection_term_stats_table_name: batch}
            while True:
                response = self.dynamodb.client.batch_write_item(RequestItems=request_items)
                unprocessed = response.get("UnprocessedItems", {})
                pending = unprocessed.get(self.collection_term_stats_table_name, [])
                if not pending:
                    break
                request_items = {self.collection_term_stats_table_name: pending}
