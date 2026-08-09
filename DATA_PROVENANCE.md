# Data provenance and verification

This document records where the two raw data sources come from and how their authenticity is
verified. It exists because the reproducibility of the whole study rests on using the correct
Apache Pig repository and the correct SEOSS extraction, and "cloned from a link someone provided"
is not a defensible basis for a dissertation. The provenance is instead established by a chain of
three independent confirmations, one of which is grounded in the dataset itself.

## The two raw sources

Two pieces of raw data sit on disk before any pipeline code runs:

- `data/seoss33/pig.sqlite` — the SEOSS 33 extraction of Apache Pig, a pre-built join of Pig's Jira
  history with its git history. Published in Data in Brief (Rath and Mader, 2019) and distributed
  via Harvard Dataverse at DOI 10.7910/DVN/PDDZ4Q.
- `data/repos/pig` — a clone of the Apache Pig source repository, cloned from the official Apache
  mirror on GitHub: `git clone https://github.com/apache/pig data/repos/pig`.

The clone is not assumed to be correct because of where it was cloned from. Its correctness is
verified against the dataset and against Pig's own commit history, as follows.

## The verification chain

### 1. The dataset declares its own git origin

The SEOSS database records which repository it was built from, in its `meta` table under the
`git_project` key. Read it directly:

```bash
sqlite3 data/seoss33/pig.sqlite "SELECT value FROM meta WHERE key='git_project';"
```

The value is a JSON object naming the source repository (`git://git.apache.org/pig.git`) and the
exact commit hash the extraction was crawled at. This is the authoritative source of record: the
dataset itself names the Apache Pig repository on Apache infrastructure. The local clone must be
verified against this, not assumed equal to it.

### 2. `github.com/apache/pig` is Apache's official mirror of that repository

Apache projects are canonically hosted on Apache infrastructure (`git.apache.org` /
`gitbox.apache.org`), and Apache maintains official read-only mirrors under the verified `apache`
organization on GitHub. So `github.com/apache/pig` is the same project the dataset names, mirrored
for convenience, rather than an unofficial fork. `git.apache.org` is the source of record; the
GitHub repo is the official mirror of it.

### 3. The commits resolve, which proves the clone contains Pig's real history

The strongest confirmation is empirical and specific to this data. When the commit resolver runs,
all twenty frozen requirements resolve to real commits in the clone, and the Layer 2 sanity check
on a long-lived file (`src/org/apache/pig/PigServer.java`) returns REAL. A wrong or fabricated
repository would fail to resolve. This result is therefore proof, from the actual data, that the
clone holds the matching project history rather than something merely plausible.

Note that SEOSS was built from a different git conversion of Pig than today's GitHub mirror, so the
commit hashes differ between the two even though every commit is present. That hash difference,
together with full commit presence, is the signature of "same project, different git conversion,"
not "different project." The commit resolver (`src/data/commit_resolver.py`) exists precisely to
bridge this by matching on message, author, and date rather than on hash.

## Re-verifying the exact crawl revision

To close the loop for the write-up, confirm that the specific revision SEOSS was crawled at is
present in the clone. Read the hash from `meta` (do not hardcode it) and check the object exists:

```bash
# print the recorded source repo and crawl hash
sqlite3 data/seoss33/pig.sqlite "SELECT value FROM meta WHERE key='git_project';"

# using the hash from that JSON, confirm the commit exists locally (prints: commit)
git -C data/repos/pig cat-file -t <crawl_hash_from_meta>
```

If `cat-file` prints `commit`, the precise revision the dataset was crawled at is present in the
repository that was cloned. That is the sentence that belongs in the methodology chapter.

## Reproducibility caveat (record for threats to validity)

The GitHub mirror is live and keeps moving, so `apache/pig` today contains commits that did not
exist when SEOSS was crawled (2017-11-21). This does not affect correctness, because every
requirement anchors on historical commits that are all present in the clone. But for strict
reproducibility a future replicator should verify against the same tree rather than a drifted HEAD.
Therefore record the exact clone commit used for this study (the current `HEAD` of the clone), or
pin the clone to it:

```bash
git -C data/repos/pig rev-parse HEAD
```

Capturing that hash alongside the results lets a replicator check out the identical tree.

## What to cite

- SEOSS 33 dataset: Rath, M. and Mader, P. (2019). The SEOSS 33 dataset — Requirements, bug
  reports, code history, and trace links for entire projects. Data in Brief, 25, 104005.
  DOI 10.7910/DVN/PDDZ4Q.
- Apache Pig source: the Apache Pig repository named by the dataset's `meta.git_project`
  (`git.apache.org/pig`), accessed via the official Apache mirror `github.com/apache/pig`, at the
  clone commit recorded for this study.
