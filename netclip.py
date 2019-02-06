#!/usr/bin/env python3
"""netclip - a network clipboard sharing application"""

import signal
import argparse
import socket
import struct
from os.path import realpath
import gi
gi.require_version('Gdk', '3.0')
gi.require_version('Gtk', '3.0')
gi.require_version('Notify', '0.7')
from gi.repository import Gdk, Gtk, GLib, Notify, GdkPixbuf

# -*- coding: utf-8 -*-
#
# netclip - a network clipboard sharing application
# Copyright (c) 2019 Endre Szabo <github@end.re>
#
# Permission is hereby granted, free of charge, to any person obtaining a
# copy of this software and associated documentation files (the "Software"),
# to deal in the Software without restriction, including without limitation
# the rights to use, copy, modify, merge, publish, distribute, sublicense,
# and/or sell copies of the Software, and to permit persons to whom the
# Software is furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL
# THE AUTHOR OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING
# FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS
# IN THE SOFTWARE.
#
# I would like to thank Adrian I Lam <me@adrianiainlam.tk> who wrote
# indicator-keyboard-led which I used as a reference when writing this
# software.

APP_NAME = 'NetClip'
APP_VERSION = '0.8'

ICON_LOCATION = 'netclip.svg'
#import gettext
#t = gettext.translation(APP_NAME, '/usr/share/locale')
#_ = t.gettext

#not there yet
def _(txt):
    return txt

class Clip:
    """Class for actual clipboard clips"""
    def __init__(self, text, max_width=30):
        self.text = text
        self.max_width = max_width

    def get_itemlabel(self):
        """returns a shortened label for menu item labels"""
        trimmed = self.text.replace("\n", " ").strip()
        if len(trimmed) > self.max_width:
            max_width = int(self.max_width/2)-1
            return "%s…%s" % (
                trimmed[:max_width],
                trimmed[-max_width:]
            )
        return trimmed
    def __eq__(self, text):
        return text == self.text

    def get_text(self):
        """return UDP MSS capped text to fit in a single ethernet packet"""
        return self.text[:1472]

    def __str__(self):
        return '<Clip "%s">' % self.get_itemlabel()

class NetClip:
    """Main Application class"""
    def __init__(self, args):

        if args.primary:
            source_clipboard = Gdk.SELECTION_PRIMARY
            destination_clipboard = Gdk.SELECTION_PRIMARY
        else:
            source_clipboard = Gdk.SELECTION_CLIPBOARD
            destination_clipboard = Gdk.SELECTION_CLIPBOARD

        #defaults
        self.clips = []
        self.received_clips = []

        self.source_clipboard = Gtk.Clipboard.get(source_clipboard)
        self.destination_clipboard = Gtk.Clipboard.get(destination_clipboard)

        self.clip_max_count = args.count
        self.menu_max_width = args.width

        self.last_sent = None

        #create menu
        self.menu = Gtk.Menu()
        self.create_menu(self.menu, autosend=args.autosend, autoreceive=args.autoreceive)

        #create status icon/appindicator
        use_appind = not args.noappint
        if use_appind:
            try:
                gi.require_version('AppIndicator3', '0.1')
                from gi.repository import AppIndicator3
            except ImportError:
                use_appind = False

        if use_appind:
            self.ind = AppIndicator3.Indicator.new(
                APP_NAME, realpath(ICON_LOCATION),
                AppIndicator3.IndicatorCategory.APPLICATION_STATUS
            )
            self.ind.set_status(AppIndicator3.IndicatorStatus.ACTIVE)
            self.ind.set_menu(self.menu)
        else:
            self.ind = Gtk.StatusIcon()
            #FIXME: deprecated
            self.ind.set_from_file(realpath(ICON_LOCATION))
            self.ind.connect('popup-menu', self.on_popup_menu)

        #setup socket
        self.multicast_group = args.address
        self.port = args.port
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 1)
        self.sock.bind(('', self.port))
        self.sock.settimeout(0.2)
        self.group = socket.inet_aton(self.multicast_group)
        mreq = struct.pack('4sL', self.group, socket.INADDR_ANY)
        self.sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)

        #setup notify
        Notify.init(APP_NAME)

        #connect signals
        self.source_clipboard.connect('owner-change', self.on_clipboard_change)
        GLib.io_add_watch(self.sock.makefile('r'), GLib.IO_IN, self.on_clip_received)

    def fill_menu_clips(self, menu, clips=None, index=0,
                        placeholder=_('empty'), group_header=_('items:'),
                        copy_clip=False):
        """A helper for filling menu items from referenced clip groups"""
        if clips:
            header = Gtk.MenuItem.new_with_label(group_header)
        else:
            #place inactive header
            header = Gtk.MenuItem.new_with_label(placeholder)
        header.set_sensitive(False)
        menu.insert(header, index)

        index += 1

        for clip in clips:
            item = Gtk.MenuItem.new_with_label(clip.get_itemlabel())
            #default action is to copy or send clip:
            if copy_clip:
                item.connect('activate', self.copy_clip, clip)
            else:
                item.connect('activate', self.send_clip, clip)
            menu.insert(item, index)
            index += 1
        return index

    def fill_menu(self, menu):
        """Removed old clip menu entries and populates menu with new values"""
        #clear up the old entries -- until separator
        separator_counter = 0
        for child in menu.get_children():
            if isinstance(child, gi.repository.Gtk.SeparatorMenuItem):
                separator_counter += 1
                if separator_counter == 2:
                    break
            menu.remove(child)
            child.destroy()

        #fill up with currect clips
        index = 0
        index = self.fill_menu_clips(menu, self.clips, index,
                                     placeholder=_('(no items to send yet)'),
                                     group_header=_('Click to send on network:'))

        menu.insert(Gtk.SeparatorMenuItem(), index)

        self.fill_menu_clips(menu, self.received_clips, index+1,
                             placeholder=_('(no items received yet)'),
                             group_header=_('Click to copy to clipboard:'), copy_clip=True)

        menu.show_all()

    def on_popup_menu(self, icon, button, time):
        """legacy menu popup helper"""
        self.menu.popup(None, None, Gtk.StatusIcon.position_menu, icon, button, time)

    def on_clipboard_change(self, source_clipboard, _):
        """Handler for clipboard change events"""

        #get clipboard content
        text = source_clipboard.wait_for_text()

        #skip this round if clipboard content is not a text
        if not text:
            return False

        #skip if new paste is the same as last one
        if self.clips and text == self.clips[0]:
            return False

        #remove duplicates
        for clip in self.clips:
            if text == clip:
                self.clips.remove(clip)

        #insert current entry
        clip = Clip(text, max_width=self.menu_max_width)
        self.clips.insert(0, clip)

        if self.autosend.get_active():
            self.send_clip(self, clip)

        #cap clips count
        if len(self.clips) > self.clip_max_count:
            self.clips.pop()

        #update application menu
        self.fill_menu(self.menu)
        return True

    def create_menu(self, menu, autosend=False, autoreceive=False):
        """Creates the application menu frame"""
        #place inactive placeholders
        menu.append(Gtk.SeparatorMenuItem())
        menu.append(Gtk.SeparatorMenuItem())

        #toggle modes
        self.autosend = Gtk.CheckMenuItem.new_with_mnemonic(_('Auto _send copied clips'))
        self.autosend.set_active(autosend)
        menu.append(self.autosend)

        self.autoreceive = Gtk.CheckMenuItem.new_with_mnemonic(_('Auto copy _received clips'))
        self.autoreceive.set_active(autoreceive)
        menu.append(self.autoreceive)

        menu.append(Gtk.SeparatorMenuItem())

        #Anyone knows how to add image as ImageMenuItem got deprecated?
        about_item = Gtk.MenuItem.new_with_mnemonic(_('_About'))
        menu.append(about_item)
        about_item.connect('activate', self.about)

        quit_item = Gtk.MenuItem.new_with_mnemonic(_('_Quit'))
        menu.append(quit_item)
        quit_item.connect('activate', self.quit)

        #populate with placeholders
        self.fill_menu(menu)

        menu.show_all()

    def send_clip(self, obj=None, clip=None):
        # pylint: disable=W0613
        """Sends the referenced clip over the network"""
        self.last_sent = clip.get_text()
        return self.sock.sendto(bytes(clip.get_text(), 'utf-8'), (self.multicast_group, self.port))

    def on_clip_received(self, *_):
        """Handler for clips received from the network"""
        data, address = self.sock.recvfrom(4096)
        #get clipboard content
        text = data.decode('utf-8')

        if self.last_sent == text:
            #This is must be our own message
            return True

        #skip this round if clipboard content is not a text
        if not text:
            return False

        #skip if new paste is the same as last one
        if self.received_clips and text == self.received_clips[0]:
            return False

        #remove duplicates
        for clip in self.received_clips:
            if text == clip:
                self.received_clips.remove(clip)

        clip = Clip(text, max_width=self.menu_max_width)

        #consider moving this block above to avoid auto dedup
        if self.autoreceive.get_active():
            self.copy_clip(self, clip)
            notification = Notify.Notification.new("Autocopied clip from %s" % address[0],
                                                   clip.get_itemlabel(), None)
        else:
            notification = Notify.Notification.new("Got clip from %s" % address[0],
                                                   clip.get_itemlabel(), None)
        notification.set_image_from_pixbuf(GdkPixbuf.Pixbuf.new_from_file(ICON_LOCATION))
        notification.show()

        #insert current entry
        self.received_clips.insert(0, clip)

        #cap clips count
        if len(self.received_clips) > self.clip_max_count:
            self.received_clips.pop()

        #update application menu
        self.fill_menu(self.menu)

        return True

    def copy_clip(self, obj=None, clip=None):
        # pylint: disable=W0613
        """Copies referenced clip to the required clipboard"""
        self.destination_clipboard.set_text(clip.get_text(), -1)
        self.destination_clipboard.store()

    def about(self, *_):
        """Definition of the about dialog"""
        aboutdialog = Gtk.AboutDialog()
        aboutdialog.set_program_name(APP_NAME)
        aboutdialog.set_version(APP_VERSION)
        aboutdialog.set_logo(GdkPixbuf.Pixbuf.new_from_file(ICON_LOCATION))
        aboutdialog.set_copyright('Copyright (C) 2019 Endre Szabo')
        aboutdialog.set_authors(['Endre Szabo'])
        aboutdialog.set_website('http://github.com/endreszabo/netclip/')
        aboutdialog.set_website_label('http://github.com/endreszabo/netclip/')
        aboutdialog.set_title("About %s" % APP_NAME)

        aboutdialog.connect('response', self.close_about)
        aboutdialog.show()

    @staticmethod
    def close_about(obj, *_):
        """Closes about window"""
        obj.destroy()

    @staticmethod
    def quit(*_):
        """Uninitialize everything and then quit"""
        Notify.uninit()
        Gtk.main_quit()

if __name__ == '__main__':
    PARSER = argparse.ArgumentParser(
        description='netclip - a network clipboard sharing application',
        formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    PARSER.add_argument('-s', '--autosend', required=False, action='store_true',
                        help='Automatically send new clipboard content')
    PARSER.add_argument('-r', '--autoreceive', required=False, action='store_true',
                        help='Automatically receive shared clipboard content')
    PARSER.add_argument('-P', '--primary', required=False, action='store_true',
                        help='Use Xorg clipboard PRIMARY (aka "middle click") '
                        'instead of CLIPBOARD (aka "Ctrl+V")')
    #                 fun fact: using vanity numbers as IP address: 22N.ET.CLI.P :)
    PARSER.add_argument('-a', '--address', required=False, default='226.38.254.7',
                        help='Multicast address to listen on and to send clips to')
    PARSER.add_argument('-p', '--port', required=False, default=10000,
                        help='Multicast port to use')
    PARSER.add_argument('-c', '--count', required=False, default=15,
                        help='Maximum clip history items count to store')
    PARSER.add_argument('-w', '--width', required=False, default=30,
                        help='Limit clip history items width to show this many characters')
    PARSER.add_argument('-n', '--noappint', required=False, action='store_true',
                        help='Do not make use of AppIndicator3 library, use legacy menus')

    NETCLIP = NetClip(args=PARSER.parse_args())
    signal.signal(signal.SIGINT, lambda signum, frame: NETCLIP.quit(None))
    Gtk.main()
