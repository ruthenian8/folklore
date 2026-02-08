# Folklore

## MySQL search backend runbook

### 1) Apply the MySQL search schema

This repository ships the SQL schema for the MySQL search index. Apply it manually once per database:

```bash
mysql -u <user> -p <db> < migrations/mysql_search_index.sql
```

### 2) Install the required NLTK data

Sentence splitting relies on the NLTK `punkt` model:

```bash
python -m nltk.downloader punkt
```

### 3) Select a search backend

Set the backend via environment variable before starting the app:

```bash
export SEARCH_BACKEND=mysql
# or
export SEARCH_BACKEND=elasticsearch
```

### 4) Build or refresh the MySQL index

Use the Flask CLI to build the MySQL sentence index:

```bash
flask search-index rebuild --truncate --batch-size 1000
```

To index a single text by id:

```bash
flask search-index text --id 123
```

### 5) MySQL FULLTEXT configuration notes

The sentence index uses a MySQL FULLTEXT index. MySQL may ignore short tokens or apply stopword filtering by default. If you need short tokens or specific languages, review and adjust the MySQL configuration options below, then rebuild the index:

- `innodb_ft_min_token_size`
- `ft_min_word_len`
- `innodb_ft_enable_stopword`
- `innodb_ft_server_stopword_table`

After changing any FULLTEXT settings, restart MySQL and rebuild the index with `flask search-index rebuild --truncate`.
