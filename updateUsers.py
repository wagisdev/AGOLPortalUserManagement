#-------------------------------------------------------------------------------
# Name:        Portal User Management
# Purpose:     This script will auto manage accounts in the system that are tied to 
#              to the enterprise IDP. If a user account is not present or
#              disabled, it will disable the account. If the account is present
#              and enabled, it will ensure the system has the account enabled.
#
# Author:      John Spence
#
# Created:     8/1/2022
# Modified:     
# Modification Purpose:
#
#
#-------------------------------------------------------------------------------

# 888888888888888888888888888888888888888888888888888888888888888888888888888888
# ------------------------------- Configuration --------------------------------
#
# ------------------------------- Dependencies ---------------------------------
#
# 888888888888888888888888888888888888888888888888888888888888888888888888888888

# Portal Config
portalURL = 'https://www.arcgis.com' #your AGOL URL or portal URL
portalUSR = '' #your AGOL/Portal user name
portalPAS = '' #your AGOL/Portal password (base64 encoded // Security through obscurity :P )

# Script Type
scriptType = 'Portal User Management'

# ADFS Config
adfsServer = 'something.something.com'
adfsRootDomain = 'something.somethingadfslike.com'
ldapUSR = r''
ldapPAS = '' #base64 encoded // Security through obscurity :P )

# Send confirmation of rebuild to
adminNotify = 'someone@something.com'
deptAdminNotify = 'someoneelse@something.com'

# Configure the e-mail server and other info here.
mail_server = 'smtprelay.something.com'
mail_from = '{} <noreply@something.com>'.format(scriptType)
mail_subject = '{} Automated Actions Notification'.format(scriptType)

# Test User Override
testUser = 'testuser@something.com' # Sends a test message showing actions that would be taken, but not.

# ------------------------------------------------------------------------------
# DO NOT UPDATE BELOW THIS LINE OR RISK DOOM AND DISPAIR!  Have a nice day!
# ------------------------------------------------------------------------------

# Import Python libraries
import arcpy
import arcgis
from arcgis.gis import GIS
import base64
import datetime
import time
import urllib
import requests
import json
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import concurrent.futures
import ldap3
from ldap3 import Server, Connection, ALL

#-------------------------------------------------------------------------------
#
#
#                                 Functions
#
#
#-------------------------------------------------------------------------------

def main():
#-------------------------------------------------------------------------------
# Name:        Function - main
# Purpose:  Starts the whole thing.
#-------------------------------------------------------------------------------

    starttime = datetime.datetime.now()
    portalCheck = signinPortal(starttime)
    usersEnabled, usersDisabled, usersDisabledAlready = getPortalUsers(portalCheck)
    sendNotification(usersEnabled, usersDisabled, usersDisabledAlready)

    return

def signinPortal(starttime):
#-------------------------------------------------------------------------------
# Name:        Function - signinPortal
# Purpose:  Signs into Portal
#-------------------------------------------------------------------------------

    portalInfo = arcpy.SignInToPortal(portalURL, portalUSR, base64.b64decode(portalPAS))
    portalDesc = arcpy.GetPortalDescription()
    portalID = portalDesc['id']

    print ('\nStartup : {}\n'.format(starttime))
    print ('******** Portal Check Completed ******** ')
    if portalID == '0123456789ABCDEF':
        print ('    - Portal connection:  Internal Portal')
        portalCheck = 1
    else:
        print ('    - Portal connection:  ArcGIS Online')
        portalCheck = 0
    print ('\n\n')

    return(portalCheck)

def ldapCheck(portalUserCheck, portalCheck):
#-------------------------------------------------------------------------------
# Name:        Function - ldapCheck
# Purpose:  
#-------------------------------------------------------------------------------

    conn = Connection(Server('LDAP://{}'.format(adfsServer)), auto_bind = True, user = ldapUSR, password = base64.b64decode(ldapPAS))

    if portalCheck != 0:
        conn.search('dc=####,dc==####,,dc==####,,dc==####,', '(&(objectclass=person)(SamAccountName={}))'.format(portalUserCheck), attributes=['Name', 'Department', 'SamAccountName', 'UserPrincipalName', 'userAccountControl'])
    else:
        conn.search('dc==####,,dc==####,,dc==####,,dc==####,', '(&(objectclass=person)(UserPrincipalName={}))'.format(portalUserCheck), attributes=['Name', 'Department', 'SamAccountName', 'UserPrincipalName', 'userAccountControl'])

    respCode = 0
    if len (conn.entries) != 0:
        results = conn.entries[0]
        portalUser = results.Name
        portalUserDept = results.Department
        portalUserSAM = results.SamAccountName
        portalUserUPN = results.UserPrincipalName
        print ('    -- Domain User exists')
        print ('    -- Department: {}'.format(portalUserDept))
        print ('    -- SAM Account: {}'.format(portalUserSAM))
        if results.userAccountControl == 514:
            respCode = 1
            print ('    -- WARNING: This account is disabled in the domain.')
    else:
        print ('    !! ERROR - DOMAIN USER DOES NOT EXIST')
        portalUserDept = None
        respCode = 1
   
    return (portalUserDept, respCode)

def getPortalUsers(portalCheck):
#-------------------------------------------------------------------------------
# Name:        Function - getPortalUsers
# Purpose:  
#-------------------------------------------------------------------------------

    usersEnabled = []
    usersDisabled = []
    usersDisabledAlready = []

    gis = GIS('Home')
    totalUsers = gis.users.counts('user_type', as_df=False)[0]['count']
    users = gis.users.search (query='', max_users=10000)
    for i in users:
        if i.idpUsername != None:
            try:
                print(i.fullName, ' | ', i.idpUsername, ' | ', i.categories, ' | ', i.disabled)
            except:
                print(i.fullName, ' | ', i.idpUsername, ' | N/A | ', i.disabled)
            portalUserCheck = i.idpUsername.lower()
            portalUserDept, respCode = ldapCheck(portalUserCheck, portalCheck)
            if respCode == 1 and i.disabled != True:
                userID = i.username
                print ('    -- Update action: DISABLING USER ACCOUNT')
                if testUser != '':
                    print ('        -- Fake Disable...')                    
                else:
                    gis.users.disable_users([userID])
                payload = (i.fullName, i.idpUsername, portalUserDept, 'AD user disabled or not found. Account Disabled.', 'Check for content, transfer training when applicable, and delete user.')
                usersDisabled.append(payload)
                print ('\n\n')
            elif respCode == 1 and i.disabled == True:
                print ('    -- Update action: None Required. Account Disabled')
                payload = (i.fullName, i.idpUsername, portalUserDept, 'No action required. Account already disabled.', 'May be seasonal worker. Check with department.')
                usersDisabledAlready.append(payload)
                print ('\n\n')
            elif respCode != 1 and i.disabled == True:
                userID = i.username
                print ('    -- Update action: Account Enabled')
                if testUser != '':
                    print ('        -- Fake Enable...')
                else:
                    gis.users.enable_users([userID])
                payload = (i.fullName, i.idpUsername, portalUserDept, 'AD user account found. Account Enabled.', 'No action required.')
                usersEnabled.append(payload)
                print ('\n\n')
            else:
                print ('    -- Update action: None Required. Domain and Account active.')
                print ('\n\n')

    return (usersEnabled, usersDisabled, usersDisabledAlready)

def sendNotification(usersEnabled, usersDisabled, usersDisabledAlready):

    UErowOutput = ''
    if len(usersEnabled) != 0:
        for ue in usersEnabled:
            ueuserFullName = ue[0]
            ueuseridpUsername = ue[1]
            ueuserDept = ue[2]
            ueuserAction = ue[3]
            ueuserRecommendedAction = ue[4]
            print (ueuserFullName, ' ', ueuseridpUsername, ' ', ueuserDept, ' ', ueuserAction)
            rowLine = '''
              <tr>
                <td>{}</td>
                <td>{}</td>
                <td>{}</td>
                <td>{}</td>
                <td>{}</td>
              </tr>
            '''.format(ueuserFullName, ueuseridpUsername, ueuserDept, ueuserAction, ueuserRecommendedAction)
            UErowOutput = UErowOutput + rowLine

        ueNotification = 1
    else:
        print ('No Notification Required.')
        ueNotification = 0

    UDrowOutput = ''
    if len(usersDisabled) != 0:
        for ud in usersDisabled:
            uduserFullName = ud[0]
            uduseridpUsername = ud[1]
            uduserDept = ud[2]
            uduserAction = ud[3]
            uduserRecommendedAction = ud[4]
            print (uduserFullName, ' ', uduseridpUsername, ' ', uduserDept, ' ', uduserAction)
            rowLine = '''
              <tr>
                <td>{}</td>
                <td>{}</td>
                <td>{}</td>
                <td>{}</td>
                <td>{}</td>
              </tr>
            '''.format(uduserFullName, uduseridpUsername, uduserDept, uduserAction, uduserRecommendedAction)
            UDrowOutput = UDrowOutput + rowLine

        udNotification = 1
    else:
        print ('No Notification Required.')
        udNotification = 0

    UArowOutput = ''
    if len(usersDisabledAlready) != 0:
        for uad in usersDisabledAlready:
            uaduserFullName = uad[0]
            uaduseridpUsername = uad[1]
            uaduserDept = uad[2]
            uaduserAction = uad[3]
            uaduserRecommendedAction = uad[4]
            print (uaduserFullName, ' ', uaduseridpUsername, ' ', uaduserDept, ' ', uaduserAction)
            rowLine = '''
              <tr>
                <td>{}</td>
                <td>{}</td>
                <td>{}</td>
                <td>{}</td>
                <td>{}</td>
              </tr>
            '''.format(uaduserFullName, uaduseridpUsername, uaduserDept, uaduserAction, uaduserRecommendedAction)
            UArowOutput = UArowOutput + rowLine

        uadNotification = 1

    else:
        print ('No Notification Required.')
        uadNotification = 0

    if (ueNotification == 1 or udNotification == 1) and uadNotification == 1:
        print ('\nPreparing notification...')

    else:
        print ('\nNo notification required to be sent. Script terminating.')

    UEpayLoadHTMLStart = '''
    <div>
    <h3 style="font-family:verdana;">Accounts Enabled</h3>
    <table>
      <tr>
        <th>User</th>
        <th>IDP UserID</th>
        <th>Department</th>
        <th>Auto Actions Taken</th>
        <th>Recommended Manual Actions</th>
      </tr>      
    '''

    if len(usersEnabled) != 0:
        UEpayLoadHTMLData = '''
        {}
        </table>
        </div>
        <br>
        '''.format(UErowOutput)
    else:
        UEpayLoadHTMLData = '''
        </table>
        <h5 style="font-family:verdana;"><center>No accounts were enabled</center></h5>
        </div>
        <br>
        '''
    UEpayLoadHTML = UEpayLoadHTMLStart + UEpayLoadHTMLData

    UDpayLoadHTMLStart = '''
    <div>
    <h3 style="font-family:verdana;">Accounts Disabled</h3>
    <table>
      <tr>
        <th>User</th>
        <th>IDP UserID</th>
        <th>Department</th>
        <th>Auto Actions Taken</th>
        <th>Recommended Manual Actions</th>
      </tr>      
    '''

    if len(usersDisabled) != 0:
        UDpayLoadHTMLData = '''
        {}
        </table>
        </div>
        <br>
        '''.format(UDrowOutput)
    else:
        UDpayLoadHTMLData = '''
        </table>
        <h5 style="font-family:verdana;"><center>No accounts were disabled</center></h5>
        </div>
        <br>
        '''
    UDpayLoadHTML = UDpayLoadHTMLStart + UDpayLoadHTMLData

    UApayLoadHTMLStart = '''
    <div>
    <h3 style="font-family:verdana;">Previous Accounts Disabled</h3>
    <table>
      <tr>
        <th>User</th>
        <th>IDP UserID</th>
        <th>Department</th>
        <th>Auto Actions Taken</th>
        <th>Recommended Manual Actions</th>
      </tr>      
    '''

    if len(usersDisabledAlready) != 0:
        UApayLoadHTMLData = '''
        {}
        </table>
        </div>
        <br>
        '''.format(UArowOutput)
    else:
        UApayLoadHTMLData = '''
        </table>
        <h5 style="font-family:verdana;"><center>No accounts were disabled</center></h5>
        </div>
        <br>
        '''
    UApayLoadHTML = UApayLoadHTMLStart + UApayLoadHTMLData

    payLoadHTMLStart = '''
    
    <html>
    <head>
    <style>
    table {
        font-family: arial, sans-serif;
        border-collapse: collapse;
        width: 100%;
    }
    td, th {
        border: 1px solid #dddddd;
        text-align: left;
        padding: 8px;
    }
    tr:nth-child(even) {
        background-color: #dddddd;
    }
    </style>
    </head>
    <body>
    <h2 style="font-family:verdana;"><b>User Management Actions</b></h2>
    '''

    payLoadHTMLEnd = '''
    
    <br>
    <div>
    <bold>*Seasonal worker accounts will auto enable when AD user account is enabled.</bold>
    </div>
    <div>
    [This is an automated system message. Please contact someone@something.com for all questions.]
    </div>
    </body>
    </html>
    '''

    payLoadHTML = payLoadHTMLStart + UDpayLoadHTML + UEpayLoadHTML + UApayLoadHTML + payLoadHTMLEnd


    payLoadTXT = 'HTML Message -- Use HTML Compliant Email'

    partTXT = MIMEText(payLoadTXT, 'plain')
    partHTML = MIMEText(payLoadHTML, 'html')
    msg = MIMEMultipart('alternative')
    msg['Subject'] = mail_subject
    msg['From'] = mail_from
    msg['X-Priority'] = '5' # 1 high, 3 normal, 5 low

    if testUser != '':

        if ueNotification != 0 or udNotification != 0:

            emailContact = testUser

            print ('Sending data to {}'.format(emailContact))
            
            msg['To'] = emailContact
            msg.attach(partTXT)
            msg.attach(partHTML)

            server = smtplib.SMTP(mail_server)

            server.sendmail(mail_from, [emailContact], msg.as_string())
            server.quit()

        else:

            print ('No notifications required.')

    else:

        if ueNotification != 0 or udNotification != 0:

            emailContact = deptAdminNotify

            print ('Sending data to {}'.format(emailContact))
            
            msg['To'] = emailContact
            msg['Cc'] = adminNotify
            msg.attach(partTXT)
            msg.attach(partHTML)

            server = smtplib.SMTP(mail_server)

            server.sendmail(mail_from, [emailContact, adminNotify], msg.as_string())
            server.quit()

        else:

            print ('No notifications required.')

    return


#-------------------------------------------------------------------------------
#
#
#                                 MAIN SCRIPT
#
#
#-------------------------------------------------------------------------------

print ('***** Starting.....')

if __name__ == '__main__':
    main()
