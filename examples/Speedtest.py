#
# Speedtest.py
# SpaceWire RMAP Benchmark
#
# 2011/06/01	K. Sakai (sakai@astro.isas.jaxa.jp)

from pyspw import SpaceWire, RMAP
import time
import threading

def execute():
	"""
	RMAP Protocol Benchmarking
	"""
	
	# Target and method
	host = raw_input('Hostname or IP address: ')
	method = -1
	while method not in (1, 2):
		method = input('Access method (1: SpW  2: RMAP): ')
	
	# Initialize SpaceWire I/F and RMAP Engine
	spwif = SpaceWire.Interface(host)
	rmap = RMAP.Engine(spwif) if method == 2 else None
	
	# Set destination
	dest = RMAP.Destination(src_address=0xfe, dest_address=0x30, dest_key=0x02, crc=RMAP.CRC_DraftF, word_width=1)
	
	# Query parameters
	saddr = input('Memory starting address: ')
	size = input('Memory size (MB): ') * 1024**2
	length = input('Access length: ')
	iteration = input('# of access: ')
	disp = input('Display frequency: ')
	threads = input('# of threads: ') if method == 2 else 1
	
	# Prepare lock if RMAP access
	lock = threading.Lock() if method == 2 else None
	
	def viaspw():
		spwif.open()
		caddr = saddr
		stime = time.time()
		for i in xrange(iteration):
			packet = RMAP.packetize(0, dest, caddr, length)
			spwif.send(packet)
			spwif.receive()
			caddr += length
			if caddr + length > saddr + size:
				caddr = saddr
			if i % disp == 0:
				print "Done: " + str(i+1)
		etime = time.time()
		
		return (stime, etime)
	
	def viarmap():			
		def worker(id):
			lock.acquire()
			print "Starting thread %d..." % id
			lock.release()
			caddr = saddr
			sock = rmap.socket(dest)
			for i in xrange(iteration):
				(data, status) = sock.read(caddr, length)
				#sock.write(caddr, data)
				assert status == 0
				assert len(data) == length
				caddr += length
				if caddr + length > saddr + size:
					caddr = saddr
				if i % disp == 0:
					print "Done(%d): " % id + str(i+1)
			
			lock.acquire()
			print "Thread(%d) completed." % id,			
			if sock.retries:
				print " %d time(s) timed out." % sock.retries
			else:
				print
			lock.release()
			
			# Terminate thread
			return

		# Start RMAP Engine
		rmap.start()
		
		# Start accessing memory
		thread_pool = [ threading.Thread(target=worker, args=[i]) for i in range(threads) ]
	
		stime = time.time()
		map(lambda thread: thread.start(), thread_pool)
		map(lambda thread: thread.join(), thread_pool)
		etime = time.time()
		
		return (stime, etime)
	
	if method == 1:
		(stime, etime) = viaspw()
	else:
		(stime, etime) = viarmap()
	
	# Show stats
	print "Transferred " + str(length * iteration * threads / 1024) + " kB in " + str(etime - stime) + " seconds."
	print "Rate: " + str(length * iteration * threads / 1024 / (etime - stime)) + " kB/s"
	print
	
	# Clean up
	if rmap:
		rmap.stop()
	spwif.close()

execute()
