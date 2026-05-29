#!/usr/bin/python3

import time
import redis
import bcrypt
import logging

# Configure logging
logger = logging.getLogger(__name__)


class Redis():
    def __init__(self, host, port, password) -> None:
        # Establish a connection to Redis
        self.redis_host = host
        self.redis_port = port
        self.redis_password = password
        self.client = None
        self.connect()
        
    def connect(self):
        try:
            self.client = redis.Redis(host=self.redis_host, port=self.redis_port, password=self.redis_password)
        except redis.ConnectionError as e:
            logger.error(f"Error connecting to Redis: {e}")
            self.client = None

    def isConnected(self):
        if self.client is None:
            self.connect()
        # Test the connection
        try:
            response = self.client.ping()
            if response:
                return True
            return False
        except redis.AuthenticationError as e:
            logger.error(f"Authentication error: {e}")
            return False
        except redis.ConnectionError as e:
            logger.error(f"Connection error: {e}")
            return False
        except Exception as e:
            logger.error(f"Unknown error: {e}")
            return False

    def setKey(self, key, value):
        try:
            return self.client.set(key, value)
        except Exception as e:
            logger.error(f"Error setting key: {e}")
            return False

    def setHash(self, key, mapping):
        try:
            return self.client.hset(key, mapping=mapping)
        except Exception as e:
            logger.error(f"Error setting hash: {e}")
            return False

    def getHash(self, key):
        try:
            data = self.client.hgetall(key)
            if not data:
                return None
            return {k.decode('utf-8'): v.decode('utf-8') for k, v in data.items()}
        except Exception as e:
            logger.error(f"Error reading hash: {e}")
            return None

    def addToSet(self, key, value):
        try:
            return self.client.sadd(key, value)
        except Exception as e:
            logger.error(f"Error adding to set: {e}")
            return False

    def removeFromSet(self, key, value):
        try:
            return self.client.srem(key, value)
        except Exception as e:
            logger.error(f"Error removing from set: {e}")
            return False

    def getSetMembers(self, key):
        try:
            return [member.decode('utf-8') for member in self.client.smembers(key)]
        except Exception as e:
            logger.error(f"Error reading set members: {e}")
            return []

    def setExpiry(self, key, seconds):
        try:
            return self.client.expire(key, seconds)
        except Exception as e:
            logger.error(f"Error setting expiry: {e}")
            return False

    def getTTL(self, key):
        try:
            return self.client.ttl(key)
        except Exception as e:
            logger.error(f"Error reading ttl: {e}")
            return -2

    def deleteKeys(self, *keys):
        try:
            return self.client.delete(*keys)
        except Exception as e:
            logger.error(f"Error deleting keys: {e}")
            return False

    def getAllRedisKeys(self, pattern):
        try:
            return [key.decode('utf-8') for key in self.client.keys(pattern)]
        except Exception as e:
            logger.error(f"Error listing redis keys: {e}")
            return []
    
    def setPassword(self, key, value):
        try:
            hashed_password = bcrypt.hashpw(value.encode('utf-8'), bcrypt.gensalt())
            return self.client.set(key+"-user", hashed_password)
        except Exception as e:
            logger.error(f"Error setting password: {e}")
            return False

    def createOrUpdateUser(self, username, password, role='user', active='1'):
        try:
            hashed_password = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
            mapping = {
                'username': username,
                'password_hash': hashed_password,
                'role': role,
                'active': str(active),
            }
            self.setHash(f'user:{username}', mapping)
            self.addToSet('users', username)
            return True
        except Exception as e:
            logger.error(f"Error creating/updating user: {e}")
            return False

    def updateUser(self, username, **fields):
        try:
            if not fields:
                return False
            return self.client.hset(f'user:{username}', mapping={k: str(v) for k, v in fields.items()})
        except Exception as e:
            logger.error(f"Error updating user: {e}")
            return False

    def getUser(self, username):
        return self.getHash(f'user:{username}')

    def listUsers(self):
        usernames = self.getSetMembers('users')
        users = []
        for username in usernames:
            user = self.getUser(username)
            if user:
                users.append(user)
        users.sort(key=lambda item: item.get('username', ''))
        return users

    def deleteUserRecord(self, username):
        try:
            self.removeFromSet('users', username)
            return self.deleteKeys(f'user:{username}')
        except Exception as e:
            logger.error(f"Error deleting user record: {e}")
            return False

    def verifyUserPassword(self, username, password):
        try:
            user = self.getUser(username)
            if not user or user.get('active', '1') != '1':
                return False
            stored_password = user.get('password_hash', '')
            return bcrypt.checkpw(password.encode('utf-8'), stored_password.encode('utf-8'))
        except Exception as e:
            logger.error(f"Error verifying user password: {e}")
            return False

    def setFileMeta(self, storage_key, mapping):
        try:
            return self.setHash(f'filemeta:{storage_key}', mapping)
        except Exception as e:
            logger.error(f"Error setting file metadata: {e}")
            return False

    def getFileMeta(self, storage_key):
        return self.getHash(f'filemeta:{storage_key}')

    def listFileMetaKeys(self):
        return self.getAllRedisKeys('filemeta:*')

    def deleteFileBundle(self, storage_key):
        try:
            return self.deleteKeys(storage_key, f'filemeta:{storage_key}')
        except Exception as e:
            logger.error(f"Error deleting file bundle: {e}")
            return False
    
    def getKey(self, key):
        if not self.client.exists(key):
            logger.warning(f"Key '{key}' does not exist.")
            return None
        data_type = self.getType(key)
        try:
            if data_type == "string":
                result = self.client.get(key)
                data = self.decode(result, data_type)
                return data
            elif data_type == "list":
                result = self.getAllRange(key)
                return result
            else:
                logger.error('data type mismatch')
                return None
        except Exception as e:
            logger.error(f"Error getting key: {e}")
            return None
        
    def authenticate_user(self, username, password):
        data_type = self.getType(username+"-user")
        try:
            stored_password = self.client.get(username+"-user")
            if stored_password:
                stored_password = self.decode(stored_password, data_type)
                if bcrypt.checkpw(password.encode('utf-8'), stored_password):
                    return True
            return False
        except Exception as e:
            logger.error(f"Error authenticating user: {e}")
            return False
    
    def deleteKey(self, key):
        try:
            return self.client.delete(key)
        except Exception as e:
            logger.error(f"Error deleting key: {e}")
            return False

    def clear_data_lrem(self, key, start_index, end_index):
        try:
            self.client.lrem(key, start_index, end_index)
        except Exception as e:
            logger.error(f"Error clearing data: {e}")

    def getAllKeys(self, pattern):
        try:
            data = self.client.keys(pattern)
            result_list = self.decode(data, 'list')
            return result_list
        except Exception as e:
            logger.error(f"Error getting all keys: {e}")
            return []

    def getType(self, key):
        try:
            data_type = self.client.type(key)
            if data_type:
                return data_type.decode()
            return data_type
        except Exception as e:
            logger.error(f"Error getting type: {e}")
            return None

    def appendRpush(self, key, data):
        try:
            return self.client.rpush(key, data)
        except Exception as e:
            logger.error(f"Error appending data to list (rpush): {e}")
            return False

    def appendLpush(self, key, data):
        try:
            return self.client.lpush(key, data)
        except Exception as e:
            logger.error(f"Error appending data to list (lpush): {e}")
            return False

    def getAllRange(self, key):
        try:
            data = self.client.lrange(key, 0, -1)
            data_type = self.getType(key)
            list_values = self.decode(data, data_type)
            return list_values
        except Exception as e:
            logger.error(f"Error getting all range: {e}")
            return []

    def getIndexLRange(self, key, start_index, end_index):
        try:
            data = self.client.lrange(key, start_index, end_index)
            data_type = self.getType(key)
            list_values = self.decode(data, data_type)
            return list_values
        except Exception as e:
            logger.error(f"Error getting index range: {e}")
            return []
    def key_exists(self,key):
        return self.client.exists(key) > 0
    def decode(self, data, data_type):
        try:
            if data_type == 'string':
                return data.decode()
            elif data_type == 'list':
                data_list = [bytes.decode() for bytes in data]
                return data_list
            elif data_type in {'set', 'zset'}:
                data_list = [bytes.decode() for bytes in (bytes if isinstance(bytes, bytes) else bytes[0] for bytes in data)]
                return data_list
            elif data_type in {'hash', 'stream', 'module', 'none'}:
                return data
            else:
                return data
        except Exception as e:
            logger.error(f"Error decoding data: {e}")
            return None

    def close(self):
        try:
            if self.client:
                self.client.close()
        except Exception as e:
            logger.error(f"Error closing connection: {e}")


# Example usage
# redis_port = "6379"
# redis_ip = "localhost"
# redis_pass = "password123"
# c = Redis(redis_ip, redis_port, redis_pass)
# c.connect()
# c.isConnected()