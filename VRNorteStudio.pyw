import sys

if len(sys.argv) > 1 and sys.argv[1] == "--knowledge-mcp":
    from vrsoft_extractor.mary.mcp_server import main as knowledge_main

    sys.argv.pop(1)
    raise SystemExit(knowledge_main())

if len(sys.argv) > 1 and sys.argv[1] == "--video-cli":
    from vrsoft_extractor.cli import main as video_main

    raise SystemExit(video_main(sys.argv[2:]))

from vrsoft_extractor.mary.frontend.app import main

main()
