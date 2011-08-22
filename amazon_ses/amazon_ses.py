#Copyright (c) 2011 Vladimir Pankratiev http://tagmask.com
#
#Permission is hereby granted, free of charge, to any person obtaining a copy
#of this software and associated documentation files (the "Software"), to deal
#in the Software without restriction, including without limitation the rights
#to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
#copies of the Software, and to permit persons to whom the Software is
#furnished to do so, subject to the following conditions:
#
#The above copyright notice and this permission notice shall be included in
#all copies or substantial portions of the Software.
#
#THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
#IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
#FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
#AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
#LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
#OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
#THE SOFTWARE.

import httplib
import urllib
import hashlib
import hmac
import logging
import base64
import datetime

# Try to import the (much faster) C version of ElementTree
try:
    from xml.etree import cElementTree as ET
except ImportError:
    from xml.etree import ElementTree as ET

log = logging.getLogger(__name__)

class AmazonSES:
    def __init__(self, accessKeyID, secretAccessKey):
        self._accessKeyID = accessKeyID
        self._secretAccessKey = secretAccessKey
        self._responseParser = AmazonResponseParser()
    
    def _getSignature(self, dateValue):
        h = hmac.new(key=self._secretAccessKey, msg=dateValue, digestmod=hashlib.sha256)
        return base64.b64encode(h.digest()).decode()
    
    def _getHeaders(self):
        headers = { 'Content-type': 'application/x-www-form-urlencoded' }
        d = datetime.datetime.utcnow()
        dateValue = d.strftime('%a, %d %b %Y %H:%M:%S GMT')
        headers['Date'] = dateValue
        signature = self._getSignature(dateValue)
        headers['X-Amzn-Authorization'] = 'AWS3-HTTPS AWSAccessKeyId=%s, Algorithm=HMACSHA256, Signature=%s' % (self._accessKeyID, signature)
        return headers
    
    def _performAction(self, actionName, params=None):
        if not params:
            params = {}
        params['Action'] = actionName
        #https://email.us-east-1.amazonaws.com/
        conn = httplib.HTTPSConnection('email.us-east-1.amazonaws.com')
        params = urllib.urlencode(params)
        conn.request('POST', '/', params, self._getHeaders())
        response = conn.getresponse()
        responseResult = response.read()
        conn.close()
        return self._responseParser.parse(actionName, response.status, response.reason, responseResult)
    
    def verifyEmailAddress(self, emailAddress):
        params = { 'EmailAddress': emailAddress }
        return self._performAction('VerifyEmailAddress', params)
    
    def deleteVerifiedEmailAddress(self, emailAddress):
        params = { 'EmailAddress': emailAddress }
        return self._performAction('DeleteVerifiedEmailAddress', params)
    
    def getSendQuota(self):
        return self._performAction('GetSendQuota')
    
    def getSendStatistics(self):
        return self._performAction('GetSendStatistics')
    
    def listVerifiedEmailAddresses(self):
        return self._performAction('ListVerifiedEmailAddresses')

    def sendEmail(self, source, toAddresses, message, replyToAddresses=[], returnPath=None, ccAddresses=None, bccAddresses=None):
        params = {'Source': source}
        for index, replyAddress in enumerate(replyToAddresses):
            params['ReplyToAddresses.member.%d' % index+1] = replyAddress
        for objName, addresses in zip(["ToAddresses", "CcAddresses", "BccAddresses"], [toAddresses, ccAddresses, bccAddresses]):
            if addresses:
                if not isinstance(addresses, basestring) and getattr(addresses, '__iter__', False):
                    for i, address in enumerate(addresses, 1):
                        params['Destination.%s.member.%d' % (objName, i)] = address
                else:
                    params['Destination.%s.member.1' % objName] = addresses
        if not returnPath:
            returnPath = source
        params['ReturnPath'] = returnPath
        params['Message.Subject.Charset'] = message.charset
        params['Message.Subject.Data'] = message.subject
        if message.bodyText:
            params['Message.Body.Text.Charset'] = message.charset
            params['Message.Body.Text.Data'] = message.bodyText
        if message.bodyHtml:
            params['Message.Body.Html.Charset'] = message.charset
            params['Message.Body.Html.Data'] = message.bodyHtml
        return self._performAction('SendEmail', params)



class EmailMessage:
    def __init__(self, subject=None, bodyHtml=None, bodyText=None):
        self.charset = 'UTF-8'
        self.subject = subject
        self.bodyHtml = bodyHtml
        self.bodyText = bodyText



class AmazonError(Exception):
    def __init__(self, errorType, code, message):
        self.errorType = errorType
        self.code = code
        self.message = message
    def __str__(self):
        return self.message

class AmazonAPIError(Exception):
    def __init__(self, message):
        self.message = message
    def __str__(self):
        return self.message


class AmazonResult:
    def __init__(self, requestId):
        self.requestId = requestId

class AmazonSendEmailResult(AmazonResult):
    def __init__(self, requestId, messageId):
        self.requestId = requestId
        self.messageId = messageId

class AmazonSendQuota(AmazonResult):
    def __init__(self, requestId, max24HourSend, maxSendRate, sentLast24Hours):
        self.requestId = requestId
        self.max24HourSend = max24HourSend
        self.maxSendRate = maxSendRate
        self.sentLast24Hours = sentLast24Hours

class AmazonSendDataPoint:
    def __init__(self, xmlResponse, member):
        self.timestamp        = datetime.datetime.strptime(xmlResponse.getChildTextFromNode(member, 'Timestamp'), '%Y-%m-%dT%H:%M:%SZ')
        self.deliveryAttempts = int(xmlResponse.getChildTextFromNode(member, 'DeliveryAttempts'))
        self.bounces          = int(xmlResponse.getChildTextFromNode(member, 'Bounces'))
        self.complaints       = int(xmlResponse.getChildTextFromNode(member, 'Complaints'))
        self.rejects          = int(xmlResponse.getChildTextFromNode(member, 'Rejects'))

class AmazonSendStatistics(AmazonResult):
    def __init__(self, requestId):
        self.requestId = requestId
        self.members = []

class AmazonVerifiedEmails(AmazonSendStatistics):
    pass

class AmazonResponseParser:
    # FIXME: This XML structure is way too rigid and complex, tastes like Java - needs more flexibility
    class XmlResponse:
        def __init__(self, str):
            self._rootElement = ET.XML(str)
            self._namespace = self._rootElement.tag[1:].split("}")[0]
        
        def checkResponseName(self, name):
            if self._rootElement.tag == self._fixTag(self._namespace, name):
                return True
            else:
                raise AmazonAPIError('ErrorResponse is invalid.')
        
        def checkActionName(self, actionName):
            if self._rootElement.tag == self._fixTag(self._namespace, ('%sResponse' % actionName)):
                return True
            else:
                raise AmazonAPIError('Response of action "%s" is invalid.' % actionName)
        
        def getChild(self, *itemPath):
            node = self._findNode(self._rootElement, self._namespace, *itemPath)
            if node != None:
                return node
            else:
                raise AmazonAPIError('Node with the specified path was not found.')
        
        def getChildText(self, *itemPath):
            node = self.getChild(*itemPath)
            return node.text
        
        def getChildFromNode(self, node, *itemPath):
            child = self._findNode(node, self._namespace, *itemPath)
            if child is not None:
                return child
            else:
                raise AmazonAPIError('Node with the specified path was not found.')

        def getChildTextFromNode(self, node, *itemPath):
            child = self.getChildFromNode (node, *itemPath)
            return child.text

        def getChildren(self, node):
            return node.getchildren()

        def _fixTag(self, namespace, tag):
            return '{%s}%s' % (namespace, tag)
        
        def _findNode(self, rootElement, namespace, *args):
            match = '.'
            for s in args:
                match += '/{%s}%s' % (namespace, s)
            return rootElement.find(match)

    
    def __init__(self):
        self._simpleResultActions = ['DeleteVerifiedEmailAddress', 'VerifyEmailAddress']
    
    def _parseSimpleResult(self, actionName, xmlResponse):
        if xmlResponse.checkActionName(actionName):
            requestId = xmlResponse.getChildText('ResponseMetadata', 'RequestId')
            return AmazonResult(requestId)
    
    def _parseSendQuota(self, actionName, xmlResponse):
        if xmlResponse.checkActionName(actionName):
            requestId = xmlResponse.getChildText('ResponseMetadata', 'RequestId')
            value = xmlResponse.getChildText('GetSendQuotaResult', 'Max24HourSend')
            max24HourSend = float(value)
            value = xmlResponse.getChildText('GetSendQuotaResult', 'MaxSendRate')
            maxSendRate = float(value)
            value = xmlResponse.getChildText('GetSendQuotaResult', 'SentLast24Hours')
            sentLast24Hours = float(value)
            return AmazonSendQuota(requestId, max24HourSend, maxSendRate, sentLast24Hours)
    
    def _parseSendStatistics(self, actionName, xmlResponse):
        if xmlResponse.checkActionName(actionName):
            requestId = xmlResponse.getChildText('ResponseMetadata', 'RequestId')
            result = AmazonSendStatistics(requestId)
            send_data_points = xmlResponse.getChild('GetSendStatisticsResult', 'SendDataPoints')
            for member in send_data_points:
                result.members.append(AmazonSendDataPoint(xmlResponse, member))
            return result
    
    def _parseListVerifiedEmails(self, actionName, xmlResponse):
        if xmlResponse.checkActionName(actionName):
            requestId = xmlResponse.getChildText('ResponseMetadata', 'RequestId')
            node = xmlResponse.getChild('ListVerifiedEmailAddressesResult', 'VerifiedEmailAddresses')
            result = AmazonVerifiedEmails(requestId)
            for addr in node:
                result.members.append(addr.text)
            return result
    
    def _parseSendEmail(self, actionName, xmlResponse):
        if xmlResponse.checkActionName(actionName):
            requestId = xmlResponse.getChildText('ResponseMetadata', 'RequestId')
            messageId = xmlResponse.getChildText('SendEmailResult', 'MessageId')
            return AmazonSendEmailResult(requestId, messageId)
    
    def _raiseError(self, xmlResponse):
        if xmlResponse.checkResponseName('ErrorResponse'):
            errorType = xmlResponse.getChildText('Error', 'Type')
            code = xmlResponse.getChildText('Error', 'Code')
            message = xmlResponse.getChildText('Error', 'Message')
            raise AmazonError(errorType, code, message)
    
    def parse(self, actionName, statusCode, reason, responseResult):
        xmlResponse = self.XmlResponse(responseResult)
        log.info('Response status code: %s, reason: %s', statusCode, reason)
        log.debug(responseResult)
        
        result = None
        if statusCode != 200:
            self._raiseError(xmlResponse)
        else:
            if actionName in self._simpleResultActions:
                result = self._parseSimpleResult(actionName, xmlResponse)
            elif actionName in ['SendEmail']:
                result = self._parseSendEmail(actionName, xmlResponse)
            elif actionName == 'GetSendQuota':
                result = self._parseSendQuota(actionName, xmlResponse)
            elif actionName == 'GetSendStatistics':
                result = self._parseSendStatistics(actionName, xmlResponse)
            elif actionName == 'ListVerifiedEmailAddresses':
                result = self._parseListVerifiedEmails(actionName, xmlResponse)
            else:
                raise AmazonAPIError('Action %s is not supported.' % (actionName,))
        return result
