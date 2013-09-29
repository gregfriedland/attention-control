#!/usr/bin/env python
#
# $Id: rec2csv.py 71 2011-12-20 20:55:57Z carlt $
#
# Copyright(c) Avatar EEG Solutions Inc. All rights reserved.
#

from os import stat
from sys import argv
from struct import unpack

def print_help():
    print """rec2csv input_file

    Convert a navtive Avatar EEG binary data file to csv file format.
    Output filename will be the same except with the .rec extension
    replaced by .csv.

    input_file
          Name of the file to convert. Must have a .rec extension.
    """

def main(input_filename):
    print "Input File: %s" % input_filename
    output_filename = input_filename.replace('.rec', '.csv')
    file_stat = stat(input_filename)
    file_size = file_stat.st_size
    if ((file_size % 3072) != 0):
        print 'Warning: input file_size %d data not contain an even number of records' % file_size
    format_string = '%d, ' * (3 + 8 - 1);
    format_string += '%d\n'
    output_file = open(output_filename, 'wb')
    input_file = open(input_filename, 'rb')
    record_index = 0
    while 1:
        data = input_file.read(3072)
        if len(data) != 3072:
            break
        if (record_index%4) == 0:
            time_soc, time_frac_sec, frame_count = unpack('!IIH', data[0:10])
            data = data[24:];
        for i in range(0, len(data), 24):
            data_tuple = (time_soc, time_frac_sec, frame_count)
            for j in range(8):
                # convert 24 bit int to 32 bit int
                value = unpack('!i',data[i+j*3:i+j*3+3]+'\0')[0] >> 8
                data_tuple += (value,)
            output_file.write(format_string % data_tuple)
        record_index += 1

    print '%d seconds worth of data' % (file_size / 3072)
    print "Output file: %s" % output_filename

if __name__ == '__main__':
    keep_terminal_open = 0
    try:
        if len(argv) != 2 or argv[1][-4:] != '.rec':
            print_help()
        else:
            main(argv[1])
    finally:
        if keep_terminal_open:
            # keep the terminal open in windows so that a user can see the results
            raw_input("\nPress enter to close this window...")


