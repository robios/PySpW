#
# RMAP.py
# SpaceWire RMAP Module
#
# 2011/05/30	K. Sakai (sakai@astro.isas.jaxa.jp)

import socket
import threading
import struct
import Queue
import time

# Configuration
Max_SID = 0x0fff

class Engine(object):
	"""
	RMAP Engine
	"""
	# Sub-class definitions
	class Receiver(threading.Thread):
		"""
		RMAP Reply Receiver
		Receives reply packets and notify back a requester.
		"""
		def __init__(self, engine):
			threading.Thread.__init__(self)
			self.engine = engine
			self.running = False
			self.setDaemon(True)
		
		def run(self):
			self.running = True
			
			# Nested *while* is for performance enhancement while enabling safe(?) thread stop
			while self.running:
				try:
					while self.running:
						tid, dest, status, data, opt = depacketize(self.engine.spwif.receive())
						reply = self.engine.replies[tid]

						# Check if transaction id is invalidated
						if reply:
							reply.put((dest, status, data, opt))
				
				except socket.timeout:
					# Continue as long as running flag is set
					pass

			# Thread stopped
			self.running = False
			return
	
	class Requester(threading.Thread):
		"""
		RMAP Command Requester
		Requester watches a request queue and sends packet(s) via SpaceWireIF
		if the queue is not empty.
		"""
		def __init__(self, engine):
			threading.Thread.__init__(self)
			self.engine = engine
			self.running = False
			self.setDaemon(True)

		def run(self):
			self.running = True
			try:
				while self.running:
					self.engine.spwif.send(self.engine.requests.get())
					self.engine.requests.task_done()
			
			except TypeError:
				# It's time to stop
				pass
			
			# Thread stopped
			self.running = False
			return

	def __init__(self, spwif, timeout=1):
		"""
		Create RMAP Engine
		
		Parameter
		---------
			spwif:		SpaceWire.Interface instance
			timeout:	timeout in seconds before retry (Default: 1)
		
		Note
		----
		* spwif will be opened if closed.
		* timeout is *not* SpaceWire interface timeout, but is timeout before resending
		  a request packet when a reply packet does not arrive.
		"""
		self.spwif = spwif
		self.timeout = timeout
		
		# Child processor handles
		self.receiver = None
		self.requester = None
		
		# Initialize pools
		self.requests = Queue.Queue()
		self.replies = [ None for i in range(Max_SID) ]
		self.timedout_sids = {}
		self.sids = range(Max_SID)
		self.sids.reverse()
		
		# Lock
		self.lock = threading.Lock()
		
		# Set SpW I/F timeout, required safe stop of child classes
		self.spwif.settimeout(1)
	
	def start(self):
		"""
		Start RMAP engine. RMAP socket read/write will not work (stop forever unless timeout is set) before starting RMAP engine.
		"""
		
		# Start SpW I/F if not started
		if not self.spwif.sock:
			self.spwif.open()
		
		# Start Receiver & Requester
		self.receiver = self.Receiver(self)
		self.requester = self.Requester(self)
		self.receiver.start()
		self.requester.start()
		
	def stop(self):
		"""
		Stop RMAP engine. May take less than 1 second.
		"""
		# Stop Receiver & Requester
		if self.receiver:
			# Stop receiver
			self.receiver.running = False
		
		if self.requester:
			# This is a little rough way to stop it, but this is the best way for requester performance.
			# Using Queue timeout will degrade performance. Don't use it.
			self.requests.put(None)
		
		self.receiver.join()
		self.requester.join()
		
	def socket(self, destination, **kwargs):
		"""
		Return new socket.
		
		Parameter
		---------
			destination:	RMAP.Destination instance
			
		Keywords (and their default values)
		-----------------------------------
			retry:			None for infinite retry, or integers for number of retries (default: None)
		"""
		return Socket(self, destination, **kwargs)

	def request(self, packet):
		self.requests.put(packet)

	def request_sid(self, reply):
		"""
		Retrieve new socket id and register reply queue.
		
		Parameter
		---------
			reply:	Socket reply queue
		"""
		# First clean up sid pool
		self.clean_sid()
		
		# Pop transaction id
		while True:
			try:
				sid = self.sids.pop()
				break
			except IndexError:
				# No more sid to pop, sleep now...				
				time.sleep(1)
				
				# Clean up again
				self.clean_sid()
		
		# Register reply to pool
		self.replies[sid] = reply
		
		return sid
	
	def return_sid(self, sid, timedout=False):
		"""
		Return socket id. Set timedout to True if transaction has timed out and put socket it to temporary socket pool.
		
		Parameter
		---------
			sid:		Socket id
			timedout:	True for timed-out transactions (Default: False)
		"""
		# Delete sid from pool
		self.replies[sid] = None
		
		if timedout:
			self.timedout_sids[sid] = time.time()
		else:
			# Append back the sid
			self.sids.append(sid)

	def clean_sid(self):
		"""
		Clean up timed-out transactions.
		"""
		if self.timedout_sids:
			self.lock.acquire()
			for item in self.timedout_sids.items():
				if time.time() - item[1] > 10:
					# 10 second older transactions should be considered free
					del self.timedout_sids[item[0]]
					self.sids.append(item[0])
			self.lock.release()
			

class Socket(object):
	"""
	RMAP Socket
	"""
	def __init__(self, engine, destination, **kwargs):
		"""
		Create RMAP Socket
		
		Parameters
		----------
			engine:			RMAP Engine (RMAP.Engine instance)
			destination:	RMAP Destination (RMAP.Destination instance)
		
		Keywords (and their default values)
		-----------------------------------
			retry:			allowed retry counts. None for infinite retry, or integers for number of retries (default: None)
		
		Note
		----
		* This should not be directly instantiated. Use RMAP.socket to create a socket instead.
		"""
		self.engine = engine
		self.dest = destination

		# Allowed retry count (default: forever)
		self.retry = kwargs.get('retry', None)
		
		# Generate reply queue and register it
		self.reply = Queue.Queue()
		self.sid = self.engine.request_sid(self.reply)
		
		# Reset accumulated retry counter
		self.retries = 0

	def __del__(self):
		# Unregister reply queue
		self.engine.return_sid(self.sid)
	
	def read(self, address, length, **kwargs):
		"""
		RMAP Read
		
		Parameters
		----------
			address:	address to read
			length:		words to read
		
		Keywords (and their default values)
		-----------------------------------
			increment:	0 for non-incremental read, 1 for incremental read (default)
			extended_address:
						extended read address (default: 0x00)

		Returns
		-------
			data:		read data or None if time out
			status:		RMAP status or -1 if time out
		
		Note
		----
		* This function is not thread-safe. Simultaneous call to this function of the *same* instance is not supported.
		  Generate new socket per thread instead.
		"""
		
		# Local retry counter
		retry = 0
		
		while True:
			# Packetize read command
			packet = packetize(self.sid, self.dest, address, length, **kwargs)
			
			# Request command
			self.engine.request(packet)
			
			# Wait for reply
			try:
				reply = self.reply.get(timeout=self.engine.timeout)
				
				# Return received data and status
				return (reply[2], reply[1])
			
			except Queue.Empty:
				# Timed out
				
				# Return socket id with timed-out flag set
				self.engine.return_sid(self.sid, timedout=True)
				
				# Force to empty reply queue, just to make it sure
				try:
					self.reply.get_nowait()
				except Queue.Empty:
					pass
				
				# Renew socket id
				self.sid = self.engine.request_sid(self.reply)
				
				# Count-up counters
				retry += 1
				self.retries += 1
				
				# Do we retry?
				if self.retry is not None and retry > self.retry:
					# Exceeded allowed retry count
					return (None, -1)
	
	def write(self, address, data, **kwargs):
		"""
		RMAP Write
		
		Parameters
		----------
			address:	address to write
			length:		words to write
		
		Allowed keywords (and theier default values)
		--------------------------------------------
			verify:		0 for not verifying CRCs before write, 1 for verifying CRCs before write (default)
			ack:		0 for non-acknowledged write, 1 for acknowledged write (default)
			increment:	0 for non-incremental write, 1 for incremental write (default)
			extended_address:
						extended read address (default: 0x00)
		Returns
		-------
			status:		RMAP status or -1 if timeout (verify = 1), or None (verify = 0)
			
		Note
		----
		* This function is not thread-safe. Simultaneous call to this function of the *same* instance is not supported.
		  Generate new socket per thread instead.
		"""
		
		# Local retry counter
		retry = 0
		
		while True:
			# packetize write command
			packet = packetize(self.sid, self.dest, address, len(data), data, **kwargs)
						
			# Request command
			self.engine.request(packet)
			
			# Acknowledgement required?
			if kwargs.get('ack', 1) == 0:
				# No acknowledgement required. Quit.
				return None
			
			# Wait for reply
			try:
				reply = self.reply.get(timeout=self.engine.timeout)
				
				# Return status
				return reply[1]
			
			except Queue.Empty:
				# Timed out
				
				# Return socket id with timed-out flag set
				self.engine.return_sid(self.sid, timedout=True)
				
				# Force to empty reply queue, just to make it sure
				try:
					self.reply.get_nowait()
				except Queue.Empty:
					pass
				
				# Renew socket id
				self.sid = self.engine.request_sid(self.reply)
				
				# Count-up counters
				retry += 1
				self.retries += 1
				
				# Do we retry?
				if self.retry is not None and retry > self.retry:
					# Exceeded allowed retry count
					return -1

class Destination(object):
	"""
	RMAP Destination
	Handles RMAP destination information.
	"""

	# Magic salt
	__slots__ = ["dest_address", "dest_key", "src_address", "crc", "word_width"]

	# Dictionary
	dictionary = {}

	def __init__(self, src_address, dest_address, dest_key=None, crc=None, word_width=None):
		"""
		Create RMAP Destination
		
		Parameters
		----------
			src_address:		source logical address
			dest_address:		destination logical address
			dest_key:			destination key (optional, default: 0x00)
			crc:				CRC type (optional, default: None)
			word_width:			word width 1, 2 or 4 (optional, default: 1)
		
		Note
		----
		* When instantiated givining *only* src_address and dest_address, other 3 parameters are looked-up
		  from the internal dictionary using the combination of given 2 parameter. If not found, default
		  values will be applied.
		* Otherwise, will use given values (use default values if not given), and store the destination to
		  the internal dictionary.
		"""
		self.dest_address = dest_address
		self.src_address = src_address
		
		if dest_key is None and crc is None and word_width is None:
			# Try lookup dictionary
			if (dest_address, src_address) in Destination.dictionary:
				# Found. Recover missing items from the dictionary
				self.dest_key, self.crc, self.word_width = Destination.dictionary[(dest_address, src_address)]
			else:
				# Not found. Use default values
				self.dest_key = dest_key if dest_key else 0x00 
				self.crc = crc
				self.word_width = word_width if word_width else 1
		else:
			# No need to lookup dictionary
			self.dest_key = dest_key if dest_key else 0x00 
			self.crc = crc
			self.word_width = word_width if word_width else 1
			
			# Store to dictionary
			Destination.dictionary[(dest_address, src_address)] = (self.dest_key, self.crc, self.word_width)

def packetize(tid, dest, address, length, data=None, **kwargs):
	"""
	RMAP Packetizer
	Packetize commands to RMAP protocol packets.
	
	For RMAP Read command, leave data as None, or interpreted as RMAP Write command.
	
	Parameters
	----------
		tid:		transaction ID
		dest:		destination
		address:	accessing address
		length:		accessing length
		data:		data to write, None to read
	
	Keywords (and their default values)
	-----------------------------------
		increment:	increment flag (default: 1)
		verify:		verify flag (default: 1)
		ack:		ack flag (default: 1)
		extended_address:
					extended address (default: 0x00)
	
	Returns
	-------
		packet:		generated RMAP packet
	"""
	
	# Initialize
	pack = struct.pack
	blength = length * dest.word_width
	
	# Packet Header (Big-Endian)
	packet = pack('BB', dest.dest_address, 0x01)
	if data is None:
		# Read command
		com = (0x1 << 6) + ((0x2 + kwargs.get('increment', 1)) << 2) + 0x0
	else:
		# Write command
		com = (0x1 << 6) + (0x8 + (kwargs.get('verify', 1) << 2) + (kwargs.get('ack', 1) << 1) + (kwargs.get('increment', 1)) << 2) + 0x0
	packet += pack('B', com)
	packet += pack('BB', dest.dest_key, dest.src_address)
	#packet += pack('BB', (tid >> 8) & 0xff, tid & 0xff)
	packet += pack('>H', tid)
	packet += pack('B', kwargs.get('extended_address', 0x00))
	packet += pack('>L', address)
	packet += pack('>BH', (blength >> 16) & 0xff, blength & 0xffff)
	packet += pack('B', calc_crc(dest.crc, packet))
	
	# Packet Data (Little-Endian)
	if data is not None:
		if dest.word_width == 1:
			packet += pack('B'*len(data), *data)
			packet += pack('B', calc_crc(dest.crc, pack('B'*len(data), *data)))
		elif dest.word_width == 2:
			packet += pack('<'+'H'*len(data), *data)
			packet += pack('B', calc_crc(dest.crc, pack('<'+'H'*len(data), *data)))
		elif dest.word_width == 4:
			packet += pack('<'+'L'*len(data), *data)
			packet += pack('B', calc_crc(dest.crc, pack('<'+'L'*len(data), *data)))
		else:
			assert False, "given word_width %d is not supported." % (dest.word_width)
			
	return packet

def depacketize(packet, check_crc=False):
	"""
	RMAP Depacketizer
	Depacketize RMAP protocol packets.
	
	Parameters
	----------
		packet:		RMAP packet to depacketize
		check_crc:	True to check CRC, False not to.
	
	Returns
	-------
		tid:		transaction ID
		dest:		destination
		status:		transaction status
		data:		data
		keywords:	rw, verify, ack, and increment flags
	"""
	# Initialize
	unpack = struct.unpack
	
	# Packet Header (Big-Endian)
	(src_address, ) = unpack('B', packet[0:1])
	assert unpack('B', packet[1:2])[0] == 0x01
	(rw, verify, ack, increment) = (lambda (com, ): ((com & 0x20) >> 5, (com & 0x10) >> 4, (com & 0x08) >> 3, (com & 0x04) >> 2))(unpack('B', packet[2:3]))
	(status, ) = unpack('B', packet[3:4])
	(dest_address, ) = unpack('B', packet[4:5])
	(tid, ) = unpack('>H', packet[5:7])
	
	# Recover destination
	dest = Destination(src_address, dest_address)
	
	if rw == 1:
		# Write reply
		(crc, ) = unpack('B', packet[7:8])
		if check_crc:
			assert crc == calc_crc(dest.crc, packet[0:7])
		
		data = None
	else:
		# Read reply
		blength = (lambda (ms, b, ls, ): (ms << 16) + (b << 8) + ls)(unpack('BBB', packet[8:11]))
		length = blength / dest.word_width
		(crc, ) = unpack('B', packet[11:12])
		if check_crc:
			assert crc == calc_crc(dest.crc, packet[0:11])
		
		# Data (Little-Endian)
		if dest.word_width == 1:
			data = unpack('B'*length, packet[12:12+blength])
		elif dest.word_width == 2:
			data = unpack('<'+'H'*length, packet[12:12+blength])
		elif dest.word_width == 4:
			data = unpack('<'+'L'*length, packet[12:12+blength])
		else:
			assert False, "given word_width %d is not supported." % (dest.word_width)

		(crc, ) = unpack('B', packet[12+blength:12+blength+1])
		if check_crc:
			assert crc == calc_crc(dest.crc, packet[12:12+blength])
	
	return tid, dest, status, data, {'rw': rw, 'verify': verify, 'ack': ack, 'increment': increment}

def calc_crc(crc, data):
	"""
	Calculate RMAP packet CRC
	
	Parameters
	----------
		crc:	CRC type
		data:	data to calculate CRC
	
	Returns
	-------
		crc:	Calculated CRC	
	"""
	
	# This is ugly, but fast
	if crc in (CRC_DraftF, CRC_52C):
		table = CRCTable_DraftF
	elif crc == CRC_DraftE:
		table = CRCTable_DraftE
	elif crc == CRC_Custom:
		table = CRCTable_Custom
	else:
		return 0x00
	
	return reduce(lambda x, y: table[(x ^ y) & 0xff], struct.unpack('B'*len(data), data), 0x00)


# CRC Mode Constants
(CRC_DraftE, CRC_DraftF, CRC_52C, CRC_Custom) = (0, 1, 2, -1)

# RMAP CRC Table
CRCTable_DraftE = ( 0x00, 0x07, 0x0e, 0x09, 0x1c, 0x1b,
	0x12, 0x15, 0x38, 0x3f, 0x36, 0x31, 0x24, 0x23, 0x2a, 0x2d, 0x70, 0x77,
	0x7e, 0x79, 0x6c, 0x6b, 0x62, 0x65, 0x48, 0x4f, 0x46, 0x41, 0x54, 0x53,
	0x5a, 0x5d, 0xe0, 0xe7, 0xee, 0xe9, 0xfc, 0xfb, 0xf2, 0xf5, 0xd8, 0xdf,
	0xd6, 0xd1, 0xc4, 0xc3, 0xca, 0xcd, 0x90, 0x97, 0x9e, 0x99, 0x8c, 0x8b,
	0x82, 0x85, 0xa8, 0xaf, 0xa6, 0xa1, 0xb4, 0xb3, 0xba, 0xbd, 0xc7, 0xc0,
	0xc9, 0xce, 0xdb, 0xdc, 0xd5, 0xd2, 0xff, 0xf8, 0xf1, 0xf6, 0xe3, 0xe4,
	0xed, 0xea, 0xb7, 0xb0, 0xb9, 0xbe, 0xab, 0xac, 0xa5, 0xa2, 0x8f, 0x88,
	0x81, 0x86, 0x93, 0x94, 0x9d, 0x9a, 0x27, 0x20, 0x29, 0x2e, 0x3b, 0x3c,
	0x35, 0x32, 0x1f, 0x18, 0x11, 0x16, 0x03, 0x04, 0x0d, 0x0a, 0x57, 0x50,
	0x59, 0x5e, 0x4b, 0x4c, 0x45, 0x42, 0x6f, 0x68, 0x61, 0x66, 0x73, 0x74,
	0x7d, 0x7a, 0x89, 0x8e, 0x87, 0x80, 0x95, 0x92, 0x9b, 0x9c, 0xb1, 0xb6,
	0xbf, 0xb8, 0xad, 0xaa, 0xa3, 0xa4, 0xf9, 0xfe, 0xf7, 0xf0, 0xe5, 0xe2,
	0xeb, 0xec, 0xc1, 0xc6, 0xcf, 0xc8, 0xdd, 0xda, 0xd3, 0xd4, 0x69, 0x6e,
	0x67, 0x60, 0x75, 0x72, 0x7b, 0x7c, 0x51, 0x56, 0x5f, 0x58, 0x4d, 0x4a,
	0x43, 0x44, 0x19, 0x1e, 0x17, 0x10, 0x05, 0x02, 0x0b, 0x0c, 0x21, 0x26,
	0x2f, 0x28, 0x3d, 0x3a, 0x33, 0x34, 0x4e, 0x49, 0x40, 0x47, 0x52, 0x55,
	0x5c, 0x5b, 0x76, 0x71, 0x78, 0x7f, 0x6a, 0x6d, 0x64, 0x63, 0x3e, 0x39,
	0x30, 0x37, 0x22, 0x25, 0x2c, 0x2b, 0x06, 0x01, 0x08, 0x0f, 0x1a, 0x1d,
	0x14, 0x13, 0xae, 0xa9, 0xa0, 0xa7, 0xb2, 0xb5, 0xbc, 0xbb, 0x96, 0x91,
	0x98, 0x9f, 0x8a, 0x8d, 0x84, 0x83, 0xde, 0xd9, 0xd0, 0xd7, 0xc2, 0xc5,
	0xcc, 0xcb, 0xe6, 0xe1, 0xe8, 0xef, 0xfa, 0xfd, 0xf4, 0xf3 )

CRCTable_DraftF = ( 0x00, 0x91, 0xe3, 0x72, 0x07, 0x96,
	0xe4, 0x75, 0x0e, 0x9f, 0xed, 0x7c, 0x09, 0x98, 0xea, 0x7b, 0x1c, 0x8d,
	0xff, 0x6e, 0x1b, 0x8a, 0xf8, 0x69, 0x12, 0x83, 0xf1, 0x60, 0x15, 0x84,
	0xf6, 0x67, 0x38, 0xa9, 0xdb, 0x4a, 0x3f, 0xae, 0xdc, 0x4d, 0x36, 0xa7,
	0xd5, 0x44, 0x31, 0xa0, 0xd2, 0x43, 0x24, 0xb5, 0xc7, 0x56, 0x23, 0xb2,
	0xc0, 0x51, 0x2a, 0xbb, 0xc9, 0x58, 0x2d, 0xbc, 0xce, 0x5f, 0x70, 0xe1,
	0x93, 0x02, 0x77, 0xe6, 0x94, 0x05, 0x7e, 0xef, 0x9d, 0x0c, 0x79, 0xe8,
	0x9a, 0x0b, 0x6c, 0xfd, 0x8f, 0x1e, 0x6b, 0xfa, 0x88, 0x19, 0x62, 0xf3,
	0x81, 0x10, 0x65, 0xf4, 0x86, 0x17, 0x48, 0xd9, 0xab, 0x3a, 0x4f, 0xde,
	0xac, 0x3d, 0x46, 0xd7, 0xa5, 0x34, 0x41, 0xd0, 0xa2, 0x33, 0x54, 0xc5,
	0xb7, 0x26, 0x53, 0xc2, 0xb0, 0x21, 0x5a, 0xcb, 0xb9, 0x28, 0x5d, 0xcc,
	0xbe, 0x2f, 0xe0, 0x71, 0x03, 0x92, 0xe7, 0x76, 0x04, 0x95, 0xee, 0x7f,
	0x0d, 0x9c, 0xe9, 0x78, 0x0a, 0x9b, 0xfc, 0x6d, 0x1f, 0x8e, 0xfb, 0x6a,
	0x18, 0x89, 0xf2, 0x63, 0x11, 0x80, 0xf5, 0x64, 0x16, 0x87, 0xd8, 0x49,
	0x3b, 0xaa, 0xdf, 0x4e, 0x3c, 0xad, 0xd6, 0x47, 0x35, 0xa4, 0xd1, 0x40,
	0x32, 0xa3, 0xc4, 0x55, 0x27, 0xb6, 0xc3, 0x52, 0x20, 0xb1, 0xca, 0x5b,
	0x29, 0xb8, 0xcd, 0x5c, 0x2e, 0xbf, 0x90, 0x01, 0x73, 0xe2, 0x97, 0x06,
	0x74, 0xe5, 0x9e, 0x0f, 0x7d, 0xec, 0x99, 0x08, 0x7a, 0xeb, 0x8c, 0x1d,
	0x6f, 0xfe, 0x8b, 0x1a, 0x68, 0xf9, 0x82, 0x13, 0x61, 0xf0, 0x85, 0x14,
	0x66, 0xf7, 0xa8, 0x39, 0x4b, 0xda, 0xaf, 0x3e, 0x4c, 0xdd, 0xa6, 0x37,
	0x45, 0xd4, 0xa1, 0x30, 0x42, 0xd3, 0xb4, 0x25, 0x57, 0xc6, 0xb3, 0x22,
	0x50, 0xc1, 0xba, 0x2b, 0x59, 0xc8, 0xbd, 0x2c, 0x5e, 0xcf )

CRCTable_52C = CRCTable_DraftF

CRCTable_Custom = ()