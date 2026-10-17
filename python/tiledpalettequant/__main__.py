import sys

if len(sys.argv) > 1 and sys.argv[1] == "cli":
    from .cli import main

    sys.exit(main(sys.argv[2:]))
else:
    from .gui import main

    main()
