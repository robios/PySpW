#
# SpaceWire.py
# SpaceWire Module
#
# 2011/05/30	K. Sakai (sakai@astro.isas.jaxa.jp)

import socket
import sys
import struct

# SSDTP2 Control Flags
DataFlag_Complete_EOP = '\x00'
DataFlag_Complete_EEP = '\x01'
DataFlag_Fragmented = '\x02'
ControlFlag_SendTimeCode = '\x30'
ControlFlag_GotTimeCode = '\x31'
ControlFlag_ChangeTxSpeed = '\x38'
ControlFlag_RegisterAccess_ReadCommand = '\x40'
ControlFlag_RegisterAccess_ReadReply = '\x41'
ControlFlag_RegisterAccess_WriteCommand = '\x50'
ControlFlag_RegisterAccess_WriteReply = '\x51'

class Interface(object):
	def __init__(self, host, port=10030):
		self.host = host
		self.port = port
		self.sock = None
		self.isOpen = False
		
	def open(self):
		try:
			self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
			#self.sock.setsockopt(socket.SOL_TCP, socket.TCP_NODELAY, 1)
			self.sock.connect((self.host, self.port))
			self.isOpen = True
		except socket.error, (value, message):
			if self.sock:
				self.sock.close()
			print "Failed to open socket: " + message
			sys.exit(1)
			
	def close(self):
		if self.sock is not None:
			self.sock.close()
		self.sock = None
		self.isOpen = False
		
	def send(self, packet):
		# SSDTP2
		header = '\x00\x00'
		length = len(packet)
		header += struct.pack('!HLL', length >> 64 & 0xffff, length >> 32 & 0xffffffff, length & 0xffffffff)
		self.sock.sendall(header + packet)
		
	def receive(self):
		# SSDTP2
		header = '\xff'
		data = ''
		
		while header[0] not in (DataFlag_Complete_EOP, DataFlag_Complete_EEP):
			header = self.sock.recv(12)
			while len(header) < 12:
				header += self.sock.recv(12 - len(header))
	
			# Parse header	
			if header[0] in (DataFlag_Complete_EOP, DataFlag_Complete_EEP, DataFlag_Fragmented):
				# Data
				fragment_size = reduce(lambda x, y: (x << 8) + y, struct.unpack('B'*len(header[2:]), header[2:]))
				tdata = ''
				while len(tdata) < fragment_size:
					tdata += self.sock.recv(fragment_size - len(tdata))
				data += tdata
				
			elif header[0] in (ControlFlag_SendTimeCode, ControlFlag_GotTimeCode):
				tc = self.sock.recv(2)
				while len(tc) < 2:
					tc += self.sock.recv(2 - len(tc))
		
				# Do nothing for time code for now
				break
	
			else:
				assert False
		
		return data
	
	def fileno(self):
		if self.isOpen:
			return self.sock.fileno()