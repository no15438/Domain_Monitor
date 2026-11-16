import argparse
import json
from .store import Store
from .demo import seed
from .server import make_server


def main():
    parser = argparse.ArgumentParser(description="Domain Monitor EventKB — local/offline phase 1")
    parser.add_argument("--db",default="data/eventkb.sqlite3")
    commands = parser.add_subparsers(dest="command",required=True)
    commands.add_parser("demo", help="seed synthetic events; never import old data")
    server = commands.add_parser("serve")
    server.add_argument("--port",type=int,default=8769)
    memory = commands.add_parser("memory")
    memory.add_argument("--out",default="memory")
    show = commands.add_parser("show")
    show.add_argument("event_id")
    show.add_argument("--valid-at")
    show.add_argument("--known-at")
    args = parser.parse_args()
    store = Store(args.db)
    if args.command == "demo":
        print(json.dumps(seed(store),ensure_ascii=False,indent=2))
    elif args.command == "memory":
        print(json.dumps(store.export_memory(args.out),ensure_ascii=False,indent=2))
    elif args.command == "show":
        print(json.dumps(store.state(args.event_id,valid_at=args.valid_at,known_at=args.known_at),ensure_ascii=False,indent=2))
    elif args.command == "serve":
        with make_server(store,args.port) as server:
            print(f"Offline EventKB: http://127.0.0.1:{server.server_port}",flush=True)
            try:
                server.serve_forever()
            except KeyboardInterrupt:
                pass


if __name__ == "__main__":
    main()
