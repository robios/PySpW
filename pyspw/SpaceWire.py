#
# SpaceWire.py
# SpaceWire Module
#
# 2011/05/30	K. Sakai (sakai@astro.isas.jaxa.jp)

import socket
import struct
import sys

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
	def __init__(self, host, port=10030, timeout=None, div=11, **kwargs):
		"""
		Create SpaceWire Interface
		
		Parameters
		----------
			host:		ip or host name to connect
			port:		port number (Default: 10030)
			timeout:	socket time-out in seconds, None for no time-out (Default: None)
			div:		divider to SpaceWire Tx clock 125MHz (0 <= div <= 63) (Default: 11)
		
		Keywords
		--------
			keepalive:	True to override system-wide keepalive, or False not to (Default: True)
			keepidle:	idle seconds before sending a keepalive packet (Default: 120)
			keepintvl:	interval seconds sending keepalive packets after the first packet (Default: 2)
			keepcnt:	maximum counts before closing socket when no reply (Default: 4)
		
		Note
		----
		* SpaceWire Tx clock = 125MHz / (div + 1)
		* keepintvl and keepcnt overrides are only supported in linux platforms so far.
		  In OS X, overriding keepidle is possible, but keepintvl is defaulted to 75000
		  and unable to override socket-wise. Use following commands to set those variables
		  (keepcnt is still not configurable though):
		
		  $ sudo sysctl -w net.inet.tcp.always_keepalive=1
		  $ sudo sysctl -w net.inet.tcp.keepidle=120000		(in milliseconds)
		  $ sudo sysctl -w net.inet.tcp.keepintvl=2000		(in milliseconds)
		
		* keepalive is currently not supported in Windows.
		"""
		self.host = host
		self.port = port
		self.timeout = timeout
		self.div = int(div)
		
		self.keepalive = kwargs.get('keepalive', True)
		self.keepidle = kwargs.get('keepidle', 120)
		self.keepintvl = kwargs.get('keepintvl', 2)
		self.keepcnt = kwargs.get('keepcnt', 4)
		
		self.sock = None
		
	def open(self):
		"""
		Connect to target. Exceptions are not handled within this function.
		"""
		
		# Create a socket
		self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
		
		# Set time-out
		self.sock.settimeout(self.timeout)
		
		# Set keepalive
		if self.keepalive:
			self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
			if hasattr(socket, 'TCP_KEEPCNT'):
				self.sock.setsockopt(socket.IPPROTO_TCP, getattr(socket, 'TCP_KEEPIDLE'), self.keepidle)
				self.sock.setsockopt(socket.IPPROTO_TCP, getattr(socket, 'TCP_KEEPINTVL'), self.keepintvl)
				self.sock.setsockopt(socket.IPPROTO_TCP, getattr(socket, 'TCP_KEEPCNT'), self.keepcnt)
			elif hasattr(socket, 'TCP_KEEPALIVE'):
				self.sock.setsockopt(socket.IPPROTO_TCP, getattr(socket, 'TCP_KEEPALIVE'), self.keepidle)
			elif sys.platform == 'darwin':
				# Mac OS X has special value 0x10 to set keepidle
				self.sock.setsockopt(socket.IPPROTO_TCP, 0x10, self.keepidle)
		
		# Connect to target
		self.sock.connect((self.host, self.port))
		
		# Set Tx clock divider
		self.settxdiv(self.div)
	
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
		Receive a packet from target.
		
		Note
		----
		* This function will block if time-out is not set and there's nothing to receive.
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
	
	def settxdiv(self, div):
		"""
		Set SpaceWire link speed
		
		Parameter:
			div:	divider to SpaceWire Tx clock 125MHz (0 <= div <= 63) (Default: 0)
		
		Note:
		* SpaceWire Tx clock = 125MHz / (div + 1)
		"""
		
		# Boundary check
		div = int(div)
		div = 0 if div < 0 else div
		div = 63 if div > 63 else div
		
		self.div = div
		
		# Set it if online
		if self.sock:
			self.sock.sendall('\x38\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x02' + struct.pack('B', div) + '\x00')
	
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