#
# MemTest.py
# Memory Tester
#
# 2011/06/06	K. Sakai (sakai@astro.isas.jaxa.jp)

from pyspw import SpaceWire, RMAP
import random
import time

def execute():
	"""
	Memory Tester
	"""
	# Ask host
	host = raw_input('Hostname or IP address: ')
	
	# Initialize SpaceWire I/F and RMAP Engine
	spwif = SpaceWire.Interface(host)
	rmap = RMAP.Engine(spwif)

	# Start RMAP Engine
	rmap.start()

	# Set destination
	dest = RMAP.Destination(dest_address=0x30, src_address=0xfe, dest_key=0x02, crc=RMAP.CRC_DraftF, word_width=1)
	sock = rmap.socket(dest)
	
	# Query parameters
	saddr = input('Memory starting address: ')
	size = input('Memory size (MB): ') * 1024**2
	mlength = input('Access size (KB): ') * 1024

	# Start Tester
	stime = time.time()
	caddr = saddr
	while caddr < saddr + size:
		length = min(mlength, saddr + size - caddr)
		rdata = tuple([ random.randint(0, 255) for i in range(length) ])
		print "Writing %d byte data to 0x%08X to 0x%08X" % (length, caddr, caddr + length)
		sock.write(caddr, rdata, verify=1)
		print "Reading %d byte data from 0x%08X to 0x%08X" % (length, caddr, caddr + length)
		data = sock.read(caddr, length)
		assert rdata == data
		caddr += length
	etime = time.time()
	
	# Closing interfaces
	rmap.stop()
	spwif.close()
	
	# Done
	print "Successfully completed in %d seconds." % (etime - stime)

execute()