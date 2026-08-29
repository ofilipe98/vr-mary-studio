import sys

if len(sys.argv) > 1 and sys.argv[1] == "--video-cli":
    from vrsoft_extractor.cli import main as video_main

    raise SystemExit(video_main(sys.argv[2:]))

from vrsoft_extractor.mary.frontend.app import main

main()
