#
# Copyright (c) 2012 Avatar EEG Solutions Inc. All rights reserved.
#

# This is a modified version of the avatareeg.py program, written to work on Mac OSX Lion (10.7.3)
# Written march 2012 by Tom Rutherford <tom@avatareeg.com>

from struct import unpack
from time import strftime, localtime
from os import SEEK_END
import time

#vars
##### EDIT THIS #######
avatar_id = "032283"  # XXX Insert the string of numbers after "Laird BTM" here
write_to_csv  = True  #
write_to_bdf  = True  #
#######################

port = "/dev/tty.LairdBTM" + avatar_id + "-SPPDev"
last_beep_time = 0


# Carl's frame class
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

#carl's dataframe class
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


# the class that actually reads data. Connects to the bluetooth device
# specified in the port variable and reads data from it. Calls
# functions to unpack and write the data to file(s)
class ReceiveDataWorker():

    def __init__(self, write_csv, write_bdf):
        self.dataframes_rxd = 0
        self.last_dataframe_num = None
        self.frames_lost = 0
        self.dataframe = DataFrame()
        self.write_csv = write_csv
        self.write_bdf = write_bdf
        self.csv_file = None
        self.bdf_file = None
        self.num_bdf_records = 0
        

    def run(self):
        max_tries = 10
        i = 1
        bdf_header = create_bdf_header(avatar_id)

        # open output files
        if self.write_csv:
                self.csv_file = open(get_filename(avatar_id, 'csv'), 'wb')
                print "Writing to %s" % get_filename(avatar_id, 'csv')
        if self.write_bdf:
                self.bdf_file = open(get_filename(avatar_id, 'bdf'), 'wb')
                print "Writing to %s" % get_filename(avatar_id, 'bdf')
                self.bdf_file.write(bdf_header)

        # set frame count and lost to 0
        #self.emit(QtCore.SIGNAL("device_rx_event(PyQt_PyObject,PyQt_PyObject)"), 0, self.bt_addr)
        #self.emit(QtCore.SIGNAL("frame_lost_event(PyQt_PyObject,PyQt_PyObject)"), 0, self.bt_addr)
 
        #connect
        #try:
        print "connecting to %s" % port
        avatarDevice = open(port, "rb")

        print "connection succeeded" 
        
        #build_frame_from_rxd_bytes(rawData)

        print "Reading..."
        while(1):  #not self.exiting:
            try:
                rawData = avatarDevice.read(4096)
            except:
                # add time out for case where we are not receiving anything
                # yet we are still connected
                # self.s.close()
                print "\n Connection Closed"
                #print 'Receive thread: Connection closed: %s' % traceback.format_exc().splitlines()[-1]
                break
            #print 'recieved %d bytes' % len(rawData)
            self.build_frame_from_rxd_bytes(rawData)
            print "    %d dataframes read. Press CTRL+C to exit.\r" % self.dataframes_rxd,

                

    def process_dataframe(self):
        # check for lost frames
        if self.last_dataframe_num != None:
            if self.dataframe.frame_num < self.last_dataframe_num:
                print 'Discarding corrupt frame: frame_num < last_dataframe (%d %d)' % (self.dataframe.frame_num, self.last_dataframe_num)
                return;

            if self.last_dataframe_num+1 != self.dataframe.frame_num:
                print 'Lost data: expected=%d actual=%d' % (self.last_dataframe_num+1, self.dataframe.frame_num)

                # increment lost sample count
                self.frames_lost += self.dataframe.frame_num - (self.last_dataframe_num+1)
                

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
                if  self.csv_file:
                    # convert 24 bit int to 32 bit int
                    value = unpack('!i',self.dataframe.data[indx+j*3:indx+j*3+3]+'\0')[0] >> 8
                    file_data_tuple += (value,)
            if  self.dataframes_rxd - last_beep_time > 100:
                print "\a"
                file_data_tuple[0] = -99
                time.sleep(.3)
                last_beep_time = self.dataframes_rxd

                                      
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
        

    def build_frame_from_rxd_bytes(self, l):
        if l == '':
            print 'Unexpected null data' 
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
                    print '1 Discard %d bytes' % len(l)
                    for c in l: print '%02X'%ord(c),
                    print
                    l = ''
                else:
                    if sync_index > 0:
                        print '2 Discard %d bytes' % sync_index
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
                    print 'Bad version of %x discard 2 bytes' % self.dataframe.version
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
                        print 'Bad frame size of %d discard 4 bytes' % self.dataframe.size
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
                        print 'Frame check failed discarding %d bytes' % self.dataframe.size
                        for c in self.dataframe.raw: print '%02X'%ord(c),
                        print

                    self.dataframe.raw = ''
                else:
                    bytes_to_add = len(l)
                    self.dataframe.raw += l[:bytes_to_add]
                l = l[bytes_to_add:]


def get_filename(device_id, ext=None):
    s = 'Avatar_EEG_' + device_id + '_'
    s += strftime("%Y-%m-%d_%H-%M-%S", localtime())
    if ext:
        s += '.' + ext
    return s

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

if __name__ == "__main__":
        rx = ReceiveDataWorker(write_to_csv, write_to_bdf)
        rx.run()
        
        #avatarDevice = open(port, "rb")
        #rawData = avatarDevice.read(1024)
        #build_frame_from_rxd_bytes(rawData)
