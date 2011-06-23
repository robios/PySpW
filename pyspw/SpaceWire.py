#
# SpaceWire.py
# SpaceWire Module
#
# 2011/05/30	K. Sakai (sakai@astro.isas.jaxa.jp)

import socket
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
	"""
	SpaceWire Interface
	
	This interface talks SSDTP2 so this can connect to sthongo and SpaceWire-to-GigabitEther converters over TCP networks.
	"""
	def __init__(self, host, port=10030, timeout=None):
		self.host = host
		self.port = port
		self.timeout = timeout
		self.sock = None
		
	def open(self):
		"""
		Connect to target. Exceptions are not handled within this function.
		"""
		self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
		self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
		self.sock.settimeout(self.timeout)
		self.sock.connect((self.host, self.port))
		
	def close(self):
		if self.sock:
			self.sock.close()
		self.sock = None
		
	def send(self, packet):
		"""
		Send a packet to target using SSDTP2 protocol.
		
		Parameter
		---------
			packet:		packet to send
		"""
		# SSDTP2
		header = '\x00\x00'
		length = len(packet)
		header += struct.pack('!HLL', length >> 64 & 0xffff, length >> 32 & 0xffffffff, length & 0xffffffff)
		self.sock.sendall(header + packet)
		
	def receive(self):
		"""
		Receive a packet from target. This function blocks if time out is not set and there's nothing to receive.
		"""
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
	
	def settimeout(self, timeout):
		"""
		Set socket time out in senconds.
		
		Parameter:
			timeout:	timeout in seconds.
		"""
		self.timeout = timeout
		if self.sock:
			self.sock.settimeout(timeout)
	
	def fileno(self):
		"""
		Return socket file number.
		"""
		if self.sock:
			return self.sock.fileno()