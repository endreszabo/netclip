# NetClip

This is a network clipboard sharing application

## Usage

```
   netclip.py [-h] [-s] [-r] [-P] [-a ADDRESS] [-p PORT] [-c COUNT] [-w WIDTH] [-n]

netclip - a network clipboard sharing application

optional arguments:
  -h, --help            show this help message and exit
  -s, --autosend        Automatically send new clipboard content (default: False)
  -r, --autoreceive     Automatically receive shared clipboard content (default: False)
  -P, --primary         Use Xorg clipboard PRIMARY (aka "middle click")
                        instead of CLIPBOARD (aka "Ctrl+V") (default: False)
  -a ADDRESS, --address ADDRESS
                        Multicast address to listen on and to send clips to (default: 226.38.254.7)
  -p PORT, --port PORT  Multicast port to use (default: 10000)
  -c COUNT, --count COUNT
                        Maximum clip history items count to store (default: 15)
  -w WIDTH, --width WIDTH
                        Limit clip history items width to show this many characters (default: 30)
  -n, --noappint        Do not make use of AppIndicator3 library, use legacy menus (default: False)
```
