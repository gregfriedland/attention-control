#!/usr/bin/env python
#
# $Id: avatareeg.py 144 2012-04-24 16:58:04Z carlt $
#
# Copyright (c) 2012 Avatar EEG Solutions Inc. All rights reserved.
#

import sys
from os import SEEK_END
import random
import socket
import bluetooth
import traceback
from struct import unpack, pack
from time import localtime, strftime, sleep, asctime
from calendar import timegm
from PyQt4 import QtCore, QtGui
from avatareeg_gui_ui import Ui_MainWindow
from threading import Lock

keep_terminal_open = True
write_to_csv_init  = False
write_to_bdf_init  = False

avatar_address_prefix = '00:16:A4:'
serial_numbers = { avatar_address_prefix + '03:22:7A' : '01000',
                   avatar_address_prefix + '00:03:B5' : '00004',
                   avatar_address_prefix + '03:22:68' : '02001w',
                   avatar_address_prefix + '03:22:6E' : '02001b',
                   avatar_address_prefix + '03:22:67' : '02002',
                   avatar_address_prefix + '03:22:86' : '02001c',
                   avatar_address_prefix + '03:22:8F' : '02003',
                   avatar_address_prefix + '03:22:6D' : '02004',
                   avatar_address_prefix + '03:22:7C' : '02005',
                   avatar_address_prefix + '03:22:7D' : '02006',
                   avatar_address_prefix + '03:22:80' : '02007',
                   avatar_address_prefix + '03:22:6C' : '02008',
                   avatar_address_prefix + '03:22:8B' : '02009',
                   avatar_address_prefix + '03:22:91' : '02010',
                   avatar_address_prefix + '03:22:66' : '02011',
                   avatar_address_prefix + '03:22:90' : '02012',
                   avatar_address_prefix + '03:22:83' : '02013',
                   avatar_address_prefix + '03:22:72' : '02014',
                   avatar_address_prefix + '03:22:82' : '02015',
                   avatar_address_prefix + '03:22:7B' : '02016',
                   avatar_address_prefix + '03:22:77' : '02017',
                   avatar_address_prefix + '03:22:63' : '02018' }

class Frame():

    header_size  = 12
    crc_size     = 0
    # header and crc for text frame with 1 byte data
    minimum_size = header_size + crc_size

    def __init__(self):
        # common to all frames
        self.raw = '' # string of raw bytes received
        self.version = 0
        self.frame_size = 0
        self.frame_type = 0
        self.crc = 0

    # returns true if valid frame false otherwise
    def check(self):
        ret = True
        if (self.frame_type != 1):
            print 'Bad frame_type: %x' % self.frame_type
            ret = False
        if (self.channels != 8):
            print 'Bad num channels: %x' % self.channels
            ret = False
        if (self.time_info):
            if (self.samples != 15):
                print 'Bad num samples: %x' % self.samples
                ret = False
        else:
            if (self.samples != 16):
                print 'Bad num samples: %x' % self.samples
                ret = False
        if self.crc_size > 0 and self.crc != 0x3939:
                print 'Bad CRC: %x' % self.crc
                ret = False
        return ret


class DataFrame(Frame):
    # called after sync, version and framesize are known
    # and all bytes have been received
    def unpack_frame(self):
        assert(len(self.raw) == self.size), (len(self.data), self.size)
        self.frame_type  = unpack('B',  self.raw[4])[0]
        self.frame_num   = unpack('!I', self.raw[5:9])[0]
        self.channels    = unpack('B',  self.raw[9])[0]
        self.samples     = unpack('!H', self.raw[10:12])[0]
        if self.crc_size > 0:
            self.data        = self.raw[12:-self.crc_size]
        else:
            self.data        = self.raw[12:]
        self.time_info   = False
        if self.frame_num & 0x80000000:
            self.frame_num -= 0x80000000
            self.time_soc, self.time_frac_sec = unpack('!II', self.data[0:8])
            self.data = self.data[24:] # remove the timestamp from the data
            self.samples -= 1
            self.time_info = True
            # print 'time info frame num: %d, time soc: %d' % (self.frame_num, self.time_soc)
        if self.crc_size > 0:
            self.crc = unpack('!H', self.raw[-crc_size:])[0]

    def print_frame_info(self):
        print '--- Dataframe ---'
        print 'sync:       ', hex(ord(self.raw[0]))
        print 'version:    ', ord(self.raw[1])
        print 'framesize:  ', self.size
        print 'frame type: ', self.frame_type
        print 'frame num:  ', self.frame_num
        print 'channels:   ', self.channels
        print 'samples:    ', self.samples
        print 'crc:        ', hex(self.crc)

# statuses: Discovered, Recording, Disconnected, Not Present

def tr(text):
    return QtGui.QApplication.translate("Form", text, None, QtGui.QApplication.UnicodeUTF8)

def log(message, device_id = None):
    m = strftime("%Y-%m-%d %H:%M:%S: ", localtime())
    if device_id:
        try:
            m += serial_numbers[device_id] + ': '
        except:
            print device_id
            raise
    m += message
    print m

def get_filename(device_id, ext=None):
    s = 'Avatar_EEG_' + serial_numbers[device_id] + '_'
    s += strftime("%Y-%m-%d_%H-%M-%S", localtime())
    if ext:
        s += '.' + ext
    return s

class TableItem(QtGui.QTableWidgetItem):
    def __init__(self, text):
        QtGui.QTableWidgetItem.__init__(self, text)
        center = QtCore.Qt.AlignHCenter + QtCore.Qt.AlignVCenter
        self.setTextAlignment(center)

class DiscoverWorker(QtCore.QThread):

    def __init__(self, main_thread, discoverCheckBox, parent = None):
        QtCore.QThread.__init__(self, parent)
        self.exiting = False
        self.discoverCheckBox = discoverCheckBox
        self.discoverCheckBox.setChecked(True)
        self.main_thread = main_thread

    def __del__(self):
        self.exiting = True
        self.wait()

    def run(self):
        while not self.exiting:
            if self.discoverCheckBox.isChecked():
                try:
                    self.main_thread.free_to_connect.acquire()
                    try:
                        devices = bluetooth.discover_devices() # default 8 seconds
                    finally:
                        self.main_thread.free_to_connect.release()
                except:
                    log('Discover thread: %s' % traceback.format_exc().splitlines()[-1])
                    log("Waiting 10 seconds for bluetooth adapter to recover")
                else:
                    self.emit(QtCore.SIGNAL("discover_complete_event(PyQt_PyObject)"),
                              devices)
            sleep(10)

class ReceiveDataWorker(QtCore.QThread):

    def __init__(self, main_thread, bt_addr, write_csv, write_bdf, nsd_ip='127.0.0.1'):
        QtCore.QThread.__init__(self, None)
        self.exiting = False
        self.dataframes_rxd = 0
        self.last_dataframe_num = None
        self.frames_lost = 0
        self.bt_addr = bt_addr
        self.nsd_ip = nsd_ip
        self.dataframe = DataFrame()
        self.write_csv = write_csv
        self.write_bdf = write_bdf
        self.csv_file = None
        self.bdf_file = None
        self.num_bdf_records = 0
        self.main_thread = main_thread

    def stop(self):
        self.exiting = True
        self.wait()

    # if the object which holds the thread gets cleaned up, your thread will die with it
    # most likely give you some kind of segmentation fault. this avoids that
    def __del__(self):
        self.exiting = True
        self.wait()

    def run(self):
        max_tries = 10
        i = 1
        while not self.exiting:
            self.s = bluetooth.BluetoothSocket(bluetooth.RFCOMM)
            try:
                self.main_thread.free_to_connect.acquire()
                try:
                    # connect to Avatar EEG device
                    self.s.connect((self.bt_addr, 1))
                finally:
                    self.main_thread.free_to_connect.release()
            except:
                log('Could not connect: %s'\
                        % traceback.format_exc().splitlines()[-1],
                    self.bt_addr)
                i += 1
                if i > max_tries:
                    log('Giving up on trying to connect', self.bt_addr)
                    return;
                log("Waiting before try %d of %d" % (i, max_tries), self.bt_addr)
                self.s.close()
                sleep(5)
            else:
                self.serial_number = serial_numbers[self.bt_addr]
                base_filename = get_filename(self.bt_addr)
                self.emit(QtCore.SIGNAL("device_connection_event(PyQt_PyObject,PyQt_PyObject,PyQt_PyObject)"),
                          True, self.bt_addr, base_filename)
                break

        if self.exiting:
            return

        try:
            self.s.settimeout(10) # only supported on Linux
        except:
            pass

        bdf_header = create_bdf_header(self.serial_number)
        # connect to Neuroserver
        if self.nsd_ip:
            self.nsd = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            try:
                self.nsd.connect((self.nsd_ip, 8336))
            except:
                self.nsd = None
            else:
                self.nsd.send('eeg\n')
                get_ok(self.nsd)
                self.nsd.send('setheader %s\n' % bdf_header)
                get_ok(self.nsd)
        else:
            self.nsd = None

        # open output files
        if self.write_csv:
            self.csv_file = open(get_filename(self.bt_addr, 'csv'), 'wb')
        if self.write_bdf:
            self.bdf_file = open(get_filename(self.bt_addr, 'bdf'), 'wb')
            self.bdf_file.write(bdf_header)

        # set frame count and lost to 0
        self.emit(QtCore.SIGNAL("device_rx_event(PyQt_PyObject,PyQt_PyObject)"),
                  0, self.bt_addr)
        self.emit(QtCore.SIGNAL("frame_lost_event(PyQt_PyObject,PyQt_PyObject)"),
                  0, self.bt_addr)

        while not self.exiting:
            try:
                l = self.s.recv(4096)
            except:
                # add time out for case where we are not receiving anything
                # yet we are still connected
                self.s.close()
                log('Receive thread: Connection closed: %s' % \
                        traceback.format_exc().splitlines()[-1], self.bt_addr)
                break
            # print 'recieved %d bytes' % len(l)
            self.build_frame_from_rxd_bytes(l)
        try:
            self.s.close()
        except:
            pass
        if self.csv_file:
            self.csv_file.close()
            log('Closed file: %s' % self.csv_file.name)
        if self.bdf_file:
            self.bdf_file.close()
            log('Closed file: %s' % self.bdf_file.name )
        self.emit(QtCore.SIGNAL("device_connection_event(PyQt_PyObject,PyQt_PyObject,PyQt_PyObject)"),
                  False, self.bt_addr, None)

    def send_set_time(self):
        set_time_command = '\xaa\x01\x00\x0a\x03\x01'
        t = localtime()
        set_time_command += pack('!I', int(timegm(t)))
        self.s.send(set_time_command)
        log('Sent set time command: %s' % asctime(t))

    def send_input_short(self):
        cmd = '\xaa\x01\x00\x0a\x03\x02'
        cmd += '\xff\x00\x00' # input short
        cmd += '\x00'            # spare
        self.s.send(cmd)
        log('Sent input short command', self.bt_addr)

    def send_input_square_wave(self):
        cmd = '\xaa\x01\x00\x0a\x03\x02'
        cmd += '\x00\xff\x00' # input short
        cmd += '\x00'            # spare
        self.s.send(cmd)
        log('Sent input to test signal command', self.bt_addr)

    def send_input_electrodes(self):
        cmd = '\xaa\x01\x00\x0a\x03\x02'
        cmd += '\x00\x00\xff' # input short
        cmd += '\x00'            # spare
        self.s.send(cmd)
        log('Sent input to normal command', self.bt_addr)

    def process_dataframe(self):
        # check for lost frames
        if self.last_dataframe_num != None:
            if self.dataframe.frame_num < self.last_dataframe_num:
                log('Discarding corrupt frame: frame_num < last_dataframe (%d %d)',
                    self.dataframe.frame_num, self.last_dataframe_num, self.bt_addr)
                return;

            if self.last_dataframe_num+1 != self.dataframe.frame_num:
                log('Lost data: expected=%d actual=%d' % (self.last_dataframe_num+1,
                                                          self.dataframe.frame_num),
                    self.bt_addr)
                # increment lost sample count
                self.frames_lost += self.dataframe.frame_num - (self.last_dataframe_num+1)
                self.emit(QtCore.SIGNAL("frame_lost_event(PyQt_PyObject,PyQt_PyObject)"),
                          self.frames_lost, self.bt_addr)

        self.last_dataframe_num = self.dataframe.frame_num
        sample_count = self.dataframe.frame_num * self.dataframe.samples
        for i in range(self.dataframe.samples):
            file_data_tuple = ()
            nsd_data_tuple = ()
            indx = i * self.dataframe.channels * 3
            if self.bdf_file:
                if self.num_bdf_records == 0:
                    bdf_record = '+0\x14\x14Start Recording\x14'
                else:
                    bdf_record = '+%0.3f\x14\x14' % (self.num_bdf_records*0.002)
                self.num_bdf_records += 1
                bdf_record += (60-len(bdf_record)) * '\x00'
            for j in range(self.dataframe.channels):
                if self.bdf_file:
                    # input is in 3 byte packed network (big endian) order while BDF is little endian
                    for k in range(3):
                        bdf_record += self.dataframe.data[indx+j*3+2-k]
                if self.nsd or self.csv_file:
                    # convert 24 bit int to 32 bit int
                    value = unpack('!i',self.dataframe.data[indx+j*3:indx+j*3+3]+'\0')[0] >> 8
                    file_data_tuple += (value,)
                    value = value >> 8 # convet to 16 bit value to place nicely with brain bay
                    # at +/-200mV, 16 bit gives resolution of 6uV/bit.
                    nsd_data_tuple += (value,)
            if self.nsd:
                format_string = '%d ' * (self.dataframe.channels - 1);
                format_string += '%d\n'
                data_string = '! %d %d ' % (sample_count+i, self.dataframe.channels)
                data_string += format_string % nsd_data_tuple
                self.nsd.send(data_string)
                get_ok(self.nsd)
            if self.csv_file:
                format_string = '%d, ' * (self.dataframe.channels - 1);
                format_string += '%d\n'
                data_string = '%d, ' % sample_count
                data_string += format_string % file_data_tuple
                self.csv_file.write(data_string)
            if self.bdf_file:
                self.bdf_file.write(bdf_record)
            sample_count += 1

        if self.bdf_file:
            # update number of records for valid BDF
            self.bdf_file.seek(236)
            self.bdf_file.write('%-8s' % self.num_bdf_records)
            self.bdf_file.seek(0, SEEK_END) # goto end of file
        self.dataframes_rxd += 1
        self.emit(QtCore.SIGNAL("device_rx_event(PyQt_PyObject,PyQt_PyObject)"),
                  self.dataframes_rxd, self.bt_addr)

    def build_frame_from_rxd_bytes(self, l):
        if l == '':
            log('Unexpected null data', self.bt_addr)
            self.rxd_bytes = ''
            self.serial_number = None
            return
        while len(l) > 0:
            # step 1 - sync byte
            # step 2 - protocol version
            # step 3 - frame size
            # step 4 - read the complete frame
            if self.dataframe.raw == '':
                # step 1 - sync byte
                try:
                    sync_index = l.index('\xaa')
                except:
                    log('1 Discard %d bytes' % len(l), self.bt_addr)
                    for c in l: print '%02X'%ord(c),
                    print
                    l = ''
                else:
                    if sync_index > 0:
                        log('2 Discard %d bytes' % sync_index, self.bt_addr)
                        for c in l[:sync_index]: print '%02X'%ord(c),
                        print
                    self.dataframe.raw = '\xaa'
                    l = l[sync_index+1:]

            elif len(self.dataframe.raw) < 2:
                # step 2 - next byte must be protocol version
                self.dataframe.version = ord(l[0])
                self.dataframe.raw += l[0]
                l = l[1:]
                if self.dataframe.version != 1:
                    log('Bad version of %x discard 2 bytes' % self.dataframe.version, self.bt_addr)
                    self.dataframe.raw = ''

            elif len(self.dataframe.raw) < 4:
                # step 3 - frame size
                bytes_needed = 4 - len(self.dataframe.raw)
                assert( bytes_needed == 1 or bytes_needed == 2)
                if len(l) < 2:
                    self.dataframe.raw += l[0]
                    l = l[1:]
                else:
                    self.dataframe.raw += l[:bytes_needed]
                    l = l[bytes_needed:]

                if len(self.dataframe.raw) == 4:
                    self.dataframe.size = unpack('!H', self.dataframe.raw[2:4])[0]
                    if self.dataframe.size < Frame.minimum_size:
                        log('Bad frame size of %d discard 4 bytes' % self.dataframe.size, self.bt_addr)
                        self.dataframe.raw = ''
            else:
                # step 4 - attempt to read the rest of the complete frame
                bytes_needed = self.dataframe.size - len(self.dataframe.raw)
                if len(l) >= bytes_needed:
                    bytes_to_add = bytes_needed
                    self.dataframe.raw += l[:bytes_to_add]
                    self.dataframe.unpack_frame()
                    # self.dataframe.print_frame_info()
                    if self.dataframe.check():
                        self.process_dataframe()
                    else:
                        log('Frame check failed discarding %d bytes' % self.dataframe.size,
                            self.bt_addr)
                        for c in self.dataframe.raw: print '%02X'%ord(c),
                        print

                    self.dataframe.raw = ''
                else:
                    bytes_to_add = len(l)
                    self.dataframe.raw += l[:bytes_to_add]
                l = l[bytes_to_add:]


class AvatarEEG(QtGui.QMainWindow):

    def __init__(self, parent=None):
        super(AvatarEEG, self).__init__()
        self.free_to_connect = Lock()
        self.ui = Ui_MainWindow()
        self.ui.setupUi(self)
        version = "$Revision: 144 $".replace( '$Revision: ', '' )[:-2]
        self.setWindowTitle(tr('Avatar EEG Driver'))
        t = 'Avatar EEG Driver version 0.%s' % version
        log(t)
        self.ui.version_label.setText(t)
        self.ui.tableWidget.setColumnWidth(1,120)
        self.ui.csvCheckBox.setChecked(write_to_csv_init)
        self.ui.bdfCheckBox.setChecked(write_to_bdf_init)


        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            s.connect(('localhost', 8336))
        except:
            log("Neuroserver not running")
        else:
            log("Neuroserver detected")
            s.close()

        self.stimer = QtCore.QTimer()
        self.device_list = {}
        log("Starting discovery thread")
        self.discover_thread = DiscoverWorker(self, self.ui.discoverCheckBox)
        self.connect(self.discover_thread,
                     QtCore.SIGNAL('discover_complete_event(PyQt_PyObject)'),
                     self.discover_complete_event)

        self.discover_thread.start()

    def closeEvent(self, event):
        log('Avatar EEG Driver Exiting')
        del self.discover_thread
        for v in self.device_list.values():
            if v[1]:
                v[1].stop()

    def discover_complete_event(self, devices):
        # check for new devices
        for bt_addr in devices:
            if bt_addr[:len(avatar_address_prefix)] == avatar_address_prefix:
                # this is an Avatar EEG Laird BTM device
                if bt_addr not in self.device_list.keys():
                    self.device_found(True, bt_addr)
                elif self.get_status(bt_addr) == 'Not Present'\
                        or self.get_status(bt_addr) == 'Disconnected':
                    self.device_found(True, bt_addr) # refound
        # check for devices that are no longer present
        for bt_addr in self.device_list.keys():
            if bt_addr not in devices:
                if self.get_status(bt_addr) != 'Not Present':
                    self.device_found(False, bt_addr)

    def device_found(self, add, bt_addr):
        if add:
            if bt_addr not in self.device_list.keys():
                row = self.ui.tableWidget.rowCount()
                self.device_list[bt_addr] = [row, None]
                self.ui.tableWidget.insertRow(row)
                self.ui.tableWidget.setItem(row, 0, TableItem(serial_numbers[bt_addr]))
                self.ui.tableWidget.setItem(row, 2, TableItem('0'))
            self.update_status('Discovered', bt_addr)
            r = ReceiveDataWorker(self, bt_addr,
                                  self.ui.csvCheckBox.isChecked(),
                                  self.ui.bdfCheckBox.isChecked())
            self.connect(r,
                         QtCore.SIGNAL('device_connection_event(PyQt_PyObject,PyQt_PyObject,PyQt_PyObject)'),
                         self.device_connection_event)
            self.connect(r,
                         QtCore.SIGNAL('device_rx_event(PyQt_PyObject,PyQt_PyObject)'),
                         self.device_rx_event)
            self.connect(r,
                         QtCore.SIGNAL('frame_lost_event(PyQt_PyObject,PyQt_PyObject)'),
                         self.frame_lost_event)
            QtCore.QObject.connect(self.ui.setTimeButton,QtCore.SIGNAL("clicked()"), r.send_set_time)
            QtCore.QObject.connect(self.ui.setInputShortButton,QtCore.SIGNAL("clicked()"), r.send_input_short)
            QtCore.QObject.connect(self.ui.setInputSquareWaveButton,QtCore.SIGNAL("clicked()"), r.send_input_square_wave)
            QtCore.QObject.connect(self.ui.setInputElectrodesButton,QtCore.SIGNAL("clicked()"), r.send_input_electrodes)
            r.start()
            self.device_list[bt_addr][1] = r
        else:
            # if status is Connected let receive thread detect disconnection
            # this handles the case where an erroneous discover may miss the device
            if self.get_status(bt_addr) != 'Connected':
                self.update_status('Not Present', bt_addr)

    def device_connection_event(self, connected, bt_addr, filename):
        if connected:
            self.update_status('Connected', bt_addr)
            row = self.device_list[bt_addr][0]
            self.ui.tableWidget.setItem(row, 4, TableItem(filename))
        else:
            # can only transition to Not Present from disconnected
            assert self.get_status(bt_addr) != 'Not Present', self.get_status(bt_addr)
            r = self.device_list[bt_addr][1]
            r.stop()
            self.device_list[bt_addr][1] = None
            self.update_status('Disconnected', bt_addr)

    def device_rx_event(self, samples, bt_addr):
        row = self.device_list[bt_addr][0]
        self.ui.tableWidget.setItem(row, 2, TableItem(str(samples)))

    def frame_lost_event(self, frames_lost, bt_addr):
        row = self.device_list[bt_addr][0]
        self.ui.tableWidget.setItem(row, 3, TableItem(str(frames_lost)))

    def update_status(self, status, bt_addr):
        log(status, bt_addr)
        row = self.device_list[bt_addr][0]
        self.ui.tableWidget.setItem(row, 1, TableItem(status))

    def get_status(self, bt_addr):
        row = self.device_list[bt_addr][0]
        return self.ui.tableWidget.item(row, 1).text()

def get_ok(s):
   s.recv(128)

def create_bdf_header(serial_number):
   header = ''
   header +=  '%-8s' % '\xff\x42\x49\x4f\x53\x45\x4d\x49'  # version
   header += '%-80s' % (serial_number + ' M 02-AUG-1951 Avatar_EEG')
   header += '%-80s' % 'Startdate 01-FEB-2012 EEG8 Avatar EEG'
   header +=  '%-8s' % '01.02.12' # start date
   header +=  '%-8s' % '01.02.12' # start time
   header +=  '%-8s' % '2560'     # bytes in header 256*10
   header += '%-44s' % 'BDF+C'    # reserved
   header +=  '%-8s' % '-1'       # number of data records
   header +=  '%-8s' % '.002'     # duration of a record
   header +=  '%-4s' % '9'        # signals in each record

   header += '%-16s' % 'BDF Annotations'    # signal label
   for i in range(1,9):
      label = 'EEG %d' % i
      header += '%-16s' % label             # signal label

   header += '%-80s' % ''                   # tranducer type
   for i in range(8):
      header += '%-80s' % 'AgCl electrodes' # tranducer type

   header +=  '%-8s' % ''                   # physical dimension
   for i in range(8):
      header +=  '%-8s' % 'uV'              # physical dimension

   header +=  '%-8s' % '-1'                 # physical min
   for i in range(8):
      header +=  '%-8s' % '-200000'         # physical min

   header +=  '%-8s' % '1'                  # physical max
   for i in range(8):
      header +=  '%-8s' % '200000'          # physical max

   header +=  '%-8s' % '-8388608'           # digital min
   for i in range(8):
      header +=  '%-8s' % '-8388608'        # digital min

   header +=  '%-8s' % '8388607'            # digital max
   for i in range(8):
      header +=  '%-8s' % '8388607'         # digital max

   header += '%-80s' % ''                   # prefiltering
   for i in range(8):
      header += '%-80s' % ''                # prefiltering

   header +=  '%-8s' % '20'                 # samples in each record - 60 bytes
   for i in range(8):
      header +=  '%-8s' % '1'               # samples in each record

   header += '%-32s' % ''                   # reserved
   for i in range(8):
      header += '%-32s' % ''                # reserved

   assert len(header) == 2560
   return header

def unit_tests():
    test_object = ReceiveDataWorker(None, avatar_address_prefix + '00:03:B5', False, False)
    test_object.nsd = None
    fullframe =  '\xaa\x01\x00\x56\x01\x00\x00\x00\x64\x08\x00\x10'
    fullframe += '\xff\xff\xfe'*(8*3)
    fullframe += '\x39\x39'
    length = 0

    # test_object.build_frame_from_rxd_bytes('')
    # test building one byte at a time
    for c in fullframe:
        assert len(test_object.dataframe.raw) == length, (length, len(test_object.dataframe.raw))
        test_object.build_frame_from_rxd_bytes(c)
        length += 1
    assert test_object.dataframes_rxd == 1, test_object.dataframes_rxd

    fullframe = fullframe[0:8] + '\x65' + fullframe[9:] # incrment frame_num
    test_object.build_frame_from_rxd_bytes(fullframe[0:-1])
    assert test_object.dataframes_rxd == 1, test_object.dataframes_rxd
    test_object.build_frame_from_rxd_bytes(fullframe[-1:])
    assert test_object.dataframes_rxd == 2, test_object.dataframes_rxd

    fullframe = fullframe[0:8] + '\x66' + fullframe[9:] # incrment frame_num
    test_object.build_frame_from_rxd_bytes(fullframe)
    assert test_object.dataframes_rxd == 3

    # test_object.build_frame_from_rxd_bytes('\xff'*Frame.minimum_size)

    fullframe = fullframe[0:8] + '\x67' + fullframe[9:] # incrment frame_num
    test_object.build_frame_from_rxd_bytes(fullframe)
    assert test_object.dataframes_rxd == 4

if __name__ == "__main__":
    try:
        unit_tests()
        app = QtGui.QApplication(sys.argv)
        MainWindow = AvatarEEG()
        MainWindow.show()
        app.exec_()
    except:
        traceback.print_exc()
        if keep_terminal_open:
            # keep open so a windows user can see the results
            raw_input("Press enter to close this window...")
