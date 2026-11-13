import argparse
import json
from dataclasses import asdict

from filelock import FileLock

from .config import Settings
from .store import Store


def main():
    parser = argparse.ArgumentParser(description="Local GTNH wiki assistant")
    parser.add_argument("--data-dir")
    sub = parser.add_subparsers(dest="command", required=True)
    scrape = sub.add_parser("scrape", help="Collect permitted wiki articles; resumes checkpoints")
    scrape.add_argument("--limit", type=int)
    scrape.add_argument("--update", action="store_true")
    scrape.add_argument("--retry-errors", action="store_true")
    scrape.add_argument("--seed", action="append")
    index = sub.add_parser("index", help="Embed changed articles locally")
    index.add_argument("--rebuild", action="store_true")
    sub.add_parser("status")
    search = sub.add_parser("search")
    search.add_argument("query")
    ask = sub.add_parser("ask")
    ask.add_argument("question")
    back = sub.add_parser("backup")
    back.add_argument("destination")
    rest = sub.add_parser("restore")
    rest.add_argument("archive")
    rest.add_argument("destination", help="An empty directory")
    args = parser.parse_args()
    settings = Settings(**({"data_dir": args.data_dir} if args.data_dir else {})).prepare()
    store = Store(settings.data_dir)
    if args.command == "status":
        output = store.stats() | {"failures": store.errors()}
    elif args.command == "scrape":
        from .scrape import crawl

        if args.limit is not None and args.limit < 1:
            parser.error("--limit must be positive")
        with FileLock(str(settings.data_dir / "writer.lock"), timeout=0):
            if args.retry_errors:
                store.retry_errors()
            output = crawl(
                store,
                settings,
                limit=args.limit,
                update=args.update,
                seeds=args.seed,
                progress=lambda x: print(x, flush=True),
            )
    elif args.command in {"index", "search", "ask"}:
        from .index import Index

        index = Index(store, settings)
        if args.command == "index":
            with FileLock(str(settings.data_dir / "writer.lock"), timeout=0):
                output = index.sync(rebuild=args.rebuild, progress=lambda x: print(x, flush=True))
        elif args.command == "search":
            output = index.search(args.query)
        else:
            from .answer import Answerer

            output = asdict(Answerer(index, settings).answer(args.question))
    elif args.command == "backup":
        from .backup import backup

        output = {"backup": str(backup(store, args.destination))}
    else:
        from .backup import restore

        output = restore(args.archive, args.destination).stats()
    print(json.dumps(output, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
