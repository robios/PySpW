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
	def __init__(self, host, port=10030, timeout=None, reconnect=True, **kwargs):
		"""
		Create SpaceWire Interface
		
		Parameters
		----------
			host:		ip or host name to connect
			port:		port number (Default: 10030)
			timeout:	socket time-out in seconds, None for no time-out (Default: None)
			reconnect:	automatically reconnect if disconnected from peer (Default: True)
		
		Keywords
		--------
			keepalive:	True to override system-wide keepalive, or False not to (Default: True)
			keepidle:	idle seconds before sending a keepalive packet (Default: 120)
			keepintvl:	interval seconds sending keepalive packets after the first packet (Default: 2)
			keepcnt:	maximum counts before closing socket when no reply (Default: 4)
		
		Note
		----
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
		
		# Keepalive
		self.keepalive = kwargs.get('keepalive', True)
		self.keepidle = kwargs.get('keepidle', 120)
		self.keepintvl = kwargs.get('keepintvl', 2)
		self.keepcnt = kwargs.get('keepcnt', 4)
		
		# Initialization
		self.sock = None
		
		# Reconnection Handling
		if reconnect:
			import threading
			self.lock_send = threading.Lock()
			self.lock_receive = threading.Lock()
		else:
			# Reconnection not required. Override functions.
			self.send = self._send
			self.receive = self._receive
	
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
		
	def close(self):
		if self.sock:
			self.sock.close()
		self.sock = None
	
	def send(self, packet):
		"""
		Send a packet to target using SSDTP2 protocol (reconnection enabled).
		
		Parameter
		---------
			packet:		packet to send
		"""
		
		while True:
			try:
				self.lock_send.acquire()
				return self._send(packet)
			except socket.error, e:
				if e.errno == 32:
					# Broken pipe. Reconnect and try again.
					print 'send: reconnecting...'
					# First thing is first. Release send lock to avoid dead-lock.
					self.lock_send.release()
					
					# Reconnect after acquiring send lock
					self.lock_receive.acquire()
					self.close()
					self.open()
					self.lock_receive.release()
					print 'send: reconnected'
				else:
					raise
			except:
				raise
			
			finally:
				# Receive lock may be already released.
				try:
					self.lock_send.release()
				except:
					pass
		
	def _send(self, packet):
		"""
		Send a packet to target using SSDTP2 protocol (reconnection disabled).
		
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
		Receive a packet from target (reconnection enabled).
		
		Note
		----
		* This function will block if time-out is not set and there's nothing to receive.
		"""
		
		while True:
			try:
				self.lock_receive.acquire()
				return self._receive()
			except socket.error, e:
				if e.errno == 104:
					# Connection reset by peer. Reconnect and try again.
					print 'receive: reconnecting...'
					# First thing is first. Release receive lock to avoid dead-lock.
					self.lock_receive.release()
					
					# Reconnect after acquiring send lock
					self.lock_send.acquire()
					self.close()
					self.open()
					self.lock_send.release()
					print 'receive: reconnected'
				else:
					raise
			except:
				raise
			
			finally:
				# Receive lock may be already released.
				try:
					self.lock_receive.release()
				except:
					pass
	
	def _receive(self):
		"""
		Receive a packet from target (reconnection disabled).
		
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