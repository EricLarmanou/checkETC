# -*- coding: utf-8 -*-
"""
Created on Tue Sep 27 14:34:30 2022

@author: Eric Larmanou, Aarhus university, Denmark
Perform QC of biomet and eddy covariance data
3 main functions are:
    -QC: perform tests on 1 specific day
    -QC_n: perform tests on a range of dates
    -ListReports: build a summary html report of all the controled days
    
it requires:
    -an ini file containg general information
    -a config file (csv), with information per data file type (Warning: editing csvl files in excel mess up the double quotes)
    -a html template file for the report: ReportTemplate.html    
    -for each data type, a header file (csv), listing the column names and some criterias
    
todo: read Input Arguments
## todo:
- zip text report and email it
- do not delete files
- handle csv update?
"""

import os
from glob import glob
import copy
from zipfile import ZipFile
import socket
import argparse # CLI arguments
import logging
import configparser #read INI files

import pandas as pd
from datetime import datetime, timedelta, date
import numpy as np

import plotly.graph_objects as go
import plotly.io as pio

pio.templates.default = pio.templates["plotly_dark"]

VerboseLevel = logging.INFO #usually logging.INFO, for debugging logging.DEBUG

def ListReports(Site, Years=None):
    #Produce a html report per year listing all the daily reports
    #if Years is provided, process the years listed, otherwise process all years present in the report folder
    
    ReadIni(Site)
    
    FolderHome = Settings['FolderHTMLReport'].split('<')[0]
    if not os.path.exists(FolderHome):
        os.makedirs(FolderHome)
        
    #init log file
    InitLogger(os.path.join(FolderHome, 'ListLog.txt'))
    
    if Years is None:
        #list year folders
        FoldersYear = sorted(glob(FolderHome + '*\\'))
    else:
        if not isinstance(Years, list):
            Years = [Years]
        FoldersYear = [os.path.join(FolderHome , str(Year)) for Year in Years]
    for FolderYear in FoldersYear:
        Year = os.path.basename(os.path.normpath(FolderYear))
        #list day folders
        FoldersDay = sorted(glob(os.path.join(FolderYear, '*\\')))
        DF_Result = pd.DataFrame()
        for FolderDay in FoldersDay:
            FileReport = os.path.join(FolderDay, 'Report.html')
            FileFlag = os.path.join(FolderDay, 'Flags.csv')
            if os.path.exists(FileReport) and os.path.exists(FileFlag):
                DF_Flag = pd.read_csv(FileFlag, index_col=[0])
                DF_Flag.index = ['<a href="' + FileReport.replace(FolderHome, '') + '">' + DF_Flag.index + '</a>']
                DF_Result = pd.concat([DF_Result, DF_Flag])
                
        Report = ClassReport(FolderHome, Year + '.html', Settings['Site'] + ' ' + Year, '') #HTML report object
        
        #add table of files
        Style = DF_Result.style.format(na_rep='')
        Style.applymap(ColorBool)
        Style.set_table_styles([{'selector': '*', 'props': [('border','1px solid beige')]}])
        Report.Append(Style.to_html(render_links=True))
        Report.Terminate()

def QC_n(Site, DateStart, DateEnd):
    for DateQC in [DateStart + timedelta(days=x) for x in range((DateEnd-DateStart).days)]:
        QC(Site, DateQC)

def QC(Site, DateCheck = None):
    #Main function to call to perform QC
    #DateCheck: date to QC. If no date specified, today is used
    
    global Settings, Report
    
    if DateCheck == None:
        DateCheck = date.today()

    Init(Site, DateCheck)
    Report = ClassReport(Settings['FolderHTMLReport'], 'Report.html', Settings['Site'] + ' ' + DateCheck.strftime('%Y-%m-%d'), '') #HTML report object
    Report.Append('<h2>Summary</h2>', False)
    Report.Append('***SUMMARY***', False)
    DF_ResultGroup = pd.DataFrame() #result table per group
    DF_Result = pd.DataFrame() #result table per file

    NumberFilesTotal = 0
    for NameGroup, Group in Settings['Config'].iterrows(): #loop through data groups
        #check if we should process it based on Process flag, and Active dates of the group
        if Group['Process'] and (Group['ActiveFrom']<=DateCheck) and (pd.isnull(Group['ActiveTo']) or (DateCheck<=Group['ActiveTo'])):
            Result = {}
            
            #retrieve the expected header
            Header = pd.read_csv(Group['FileHeader'], index_col=0)
            
            IsBM = 'BM' == Group['FILE_TYPE']
            IsEC = 'EC' == Group['FILE_TYPE']
            
            #retrieve the files matching the group file mask for the date we are processing
            PathMask = os.path.join(Group['Folder'], Group['FileMask'])
            PathMask = PathMask.replace('<YYYY>', Settings['Year'])
            PathMask = PathMask.replace('<MM>', Settings['Month'])
            PathMask = PathMask.replace('<DD>', Settings['Day'])
            Files = sorted(glob(PathMask))
            if IsEC:
                #for EC files, we cannot use file names because the 30m-file ending at midnight is actually from the day before, so we use a filter based on datetime
                DateStart = datetime.combine(DateCheck, datetime.min.time())
                DateEnd = datetime.combine(DateCheck, datetime.min.time()) + timedelta(days=1)
                DateFiles = [FileName2Date(os.path.basename(File)) for File in Files]
                Files = [Files[Index] for Index, DateFile in enumerate(DateFiles) if ((DateStart<DateFile)and(DateFile<=DateEnd))]
            
            #check the number of files
            NumberFiles = len(Files)
            NumberFilesTotal += NumberFiles
            OkNbFiles = NumberFiles == Group['NumberFiles']
            if OkNbFiles:
                Report.Append('<h2>' + NameGroup + ': detected files: ' + '<span style="color: rgb(0,255,0);">' + str(NumberFiles) + '/' + str(Group['NumberFiles']) + '</span>' + '</h2>', False) #show numbers in green
            else:
                Report.Append('<h2>' + NameGroup + ': detected files: ' + '<span style="color: rgb(255,0,0);">' + str(NumberFiles) + '/' + str(Group['NumberFiles']) + '</span>' + '</h2>', False) #show numbers in red

            if Files:
                for File in Files: #loop through the data files
                    BaseName = os.path.basename(File)
                    logger.info('Process ' + NameGroup + '\\' + BaseName)
                    Link = '<a href="' + NameGroup + '_' + BaseName + '.html">' + BaseName + '</a>'
                    Report.Append('<h3>' + Link + '</h3>', False)
                    
                    Result['OkImportation'] = True
                    if Group.FILE_COMPRESS == '.zip':
                        Result['OkImportation'] = TestZip(File, Group.FILE_EXTENSION)
                    
                    if Result['OkImportation']:
                        DF_data, Result['OkImportation'] = LoadFile(Group, File, Header)
                        
                        #perform tests---------------------------------------------------------------
                        if Result['OkImportation']:
                            #test if corrupted file, missing columns, or some fields empty
                            Result['OkMissing'] = (DF_data != '').all(None)
                            if Result['OkMissing']:
                                #test header
                                Result['OkHeader'] = TestHeader(DF_data, Group.FILE_HEAD_VARS, Header.index.tolist())
                                DF_data = DF_data.rename(columns=lambda x: x.strip('"'))
                                Result['OkNbColumns'] = TestNbColumns(DF_data)
                                if IsEC:
                                    Result['OkDiagnosticByte'] = TestDiagnosticByte(DF_data, 'GA_DIAG_CODE')
                                    Result['OkTimeEC'] = TestTimeEC(DF_data)
                                    #Result['OkDiagnosticByte2'] = TestDiagnosticByte2(DF_data, 'Diagnostic Value 2')
                                    #Result[''] = TestDiagnosticByteCH4(DF_data)
                                    DateFile = FileName2Date(BaseName)
                                elif IsBM:
                                    DateFile = datetime.combine(DateCheck, datetime.min.time()) + timedelta(days=1)
                                    
                                Result['OkDates'] = TestDates(DF_data, DateFile, 0.5)
                                Result['OkNbRecords'] = TestNbRecords(DF_data, int(24*60*60 / Group['NumberFiles'] / Group['Period']))
                                Result['OkGaps'] = TestGaps(DF_data, Group['Period'])
                                Result['OkNum'] = TestNum(DF_data, Header)
                                if Result['OkNum']:
                                    Result['Oknan'] = TestNaN(DF_data, Header)
                                    Result['OkRange'], NbOutRange = TestRange(DF_data, Header)
                                    OutputFigures(DF_data, Header, NameGroup, BaseName, DateCheck)
                            
                    #add file result to all the results
                    DF_Result = pd.concat([DF_Result,
                                          pd.DataFrame({'Group':NameGroup , 'Name':Link} | Result, index=[0]).astype(object)],
                                          ignore_index=True)
                
                OkData = DF_Result.loc[DF_Result.Group == NameGroup, [x for x in DF_Result.columns.tolist() if x[0:2]=='Ok']].all(None)
            else:
                OkData = np.nan
            
            DF_ResultGroup = pd.concat([DF_ResultGroup,
                                        pd.DataFrame({'Group':NameGroup, 'OkNumberFile':OkNbFiles, 'NumberFile':str(NumberFiles) + '/' + str(Group['NumberFiles']), 'OkData': OkData}, index=[NameGroup]).astype(object)], 
                                        ignore_index=True)
    
    logging.shutdown()
    
    if NumberFilesTotal == 0:
        filelist = glob(os.path.join(Settings['FolderHTMLReport'], '*'))
        for f in filelist:
            os.remove(f)
        os.rmdir(Settings['FolderHTMLReport'])
    elif not DF_ResultGroup.empty:
        #add summary table of groups
        Style = DF_ResultGroup.loc[:,['Group','OkNumberFile','NumberFile','OkData']].style.format(na_rep='')
        Style.applymap(ColorBool, subset=DF_ResultGroup.columns[DF_ResultGroup.dtypes==object])
        Style.applymap(ColorNbFiles, subset='NumberFile')
        Style.set_table_styles([{'selector': '*', 'props': [('border','1px solid beige')]}])
        Style.hide(axis="index")
        Summary = Style.to_html()
        
        #add summary table of files
        Style = DF_Result.style.format(na_rep='')
        Style.applymap(ColorBool, subset=DF_Result.columns[DF_Result.dtypes==object])
        Style.set_table_styles([{'selector': '*', 'props': [('border','1px solid beige')]}])
        Style.hide(axis="index")
        Summary += Style.to_html(render_links=True)
        Report.FileContent = Report.FileContent.replace('***SUMMARY***', Summary)
        
        #terminate the report
        Report.Terminate()
        
        #save short result to as csv file
        DF_Flags = pd.DataFrame(DF_ResultGroup.OkData & DF_ResultGroup.OkNumberFile).transpose()
        DF_Flags.index = [DateCheck]
        DF_Flags.columns = DF_ResultGroup.Group
        DF_Flags.to_csv(os.path.join(Settings['FolderHTMLReport'], 'Flags.csv'))

def LoadFile(Group, File, Header):
    Columns = Header.index
    if int(Group.FILE_HEAD_NUM) == 0:
        skiprows = None
        RowHeader = None
    else:
        skiprows = list(range(0,int(Group.FILE_HEAD_NUM)))
        if int(Group.FILE_HEAD_VARS) == 0:
            RowHeader = None
        else:
            skiprows.pop(Group.FILE_HEAD_VARS-1)
            RowHeader = 0
            Columns = None
            
    if 'NaN' in Group.FILE_MISSING_VALUE:
        #allow importation of uncorrected files from Campbell loggers: the FILE_MISSING_VALUE is "NaN", but Campbell loggers produce "NAN". This has to be corrected before uploading files to ETC as their processing do not accept NAN (for the moment)
        na = [Group.FILE_MISSING_VALUE, Group.FILE_MISSING_VALUE.upper()]
    else:
        na = [Group.FILE_MISSING_VALUE]
    
    #try to load the data file---------------------------------------------------
    Ok = True
    try:
        #load 1 row to detect the date format
        DF_spl = pd.read_csv(File, skiprows=skiprows, header=RowHeader, nrows=1, dtype=str)
        LenDate = len(DF_spl.iat[0,0])
        if LenDate == 12:
            DateFormat = '%Y%m%d%H%M'
        elif LenDate == 14:
            DateFormat = '%Y%m%d%H%M%S'
        elif LenDate > 14:
            DateFormat = '%Y%m%d%H%M%S.%f'
        
        #add quotes if needed
        if Group.FILE_TIMESTAMP == 'Quotes':
            DateFormat = '"' + DateFormat + '"'
        
        # function to convert string into date
        dateparse = lambda x: datetime.strptime(x, DateFormat)
        
        DF_data = pd.read_csv(File, skiprows=skiprows, header=RowHeader, parse_dates=[0], date_parser=dateparse, na_values = na, keep_default_na = False, quoting=3, names=Columns)
    except Exception as e: # work on python 3.x
        DF_data = None
        Ok = False
        logger.info("Unexpected error:", str(e))
    return DF_data, Ok

def ColorBool(val):
    #format colors of html table
    if val == True:
        return 'color: lightgreen' 
    elif val == False:
        return 'color: red'

def ColorNbFiles(val):
    #format colors of html table
    val = val.split('/')
    if val[0]==val[1]:
        color = 'lightgreen'
    else:
        color = 'red'
    return 'color: %s' % color

def FileName2Date(BaseName):
    #return the date contained in the data file name
    Extension = os.path.splitext(BaseName)[1]
    if Extension == '.zip':
        DateFile = datetime.strptime(BaseName[10:22], '%Y%m%d%H%M') # 'GL-ZaF_EC_202207190030_L02_F01.zip'
    elif Extension == '.ghg':
        DateFile = datetime.strptime(BaseName[0:17], '%Y-%m-%dT%H%M%S') # '2022-07-19T233000_MM2-GL-ZaF-AIU-1915.ghg'
    return DateFile

def GetInputArguments():
    #load input parameters, or use default---------------------------------
    parser = argparse.ArgumentParser(prog='checkETC', description='Check ETC files. Examples: "checkETC GL-ZaF -d now -y now" or "checkETC GL-ZaF -d 2022-01-01 -e 2022-01-31 -y 2022"')
    parser.add_argument('Site', type=str, nargs='?', help='name of the site to check must match the section name in the ini file (for ex. "GL-ZaF").')
    parser.add_argument('-d', dest='DateStart', metavar='DateStart', type=str, nargs='?', help='Date of the 1st day to check, format yyyy-mm-dd or "now". If not provided no data file is checked.')
    parser.add_argument('-e', dest='DateEnd', metavar='DateEnd', type=str, nargs='?', help='Date of the last day to check format yyyy-mm-dd or "now". If not provided only the data of DateStart is checked.')
    parser.add_argument('-y', dest='YearsReport', metavar='YearsReport', type=str, nargs='?', help='years used to produce yearly reports, comma-serparated-list of years or "now". If not provided, no yearly report is produced.')

    args = parser.parse_args()
    Site =  args.Site
    
    if args.DateStart is None:
        DateStart = None
    elif args.DateStart.lower() == "now":
        DateStart = date.today()
    else:
        DateStart = datetime.strptime(args.DateStart, '%Y-%m-%d').date()
        
    if args.DateEnd is None:
        DateEnd = None
    elif args.DateEnd.lower() == "now":
        DateEnd = date.today()
    else:
        DateEnd = datetime.strptime(args.DateEnd, '%Y-%m-%d').date()
    
    if args.YearsReport is None:
        YearsReport = None
    elif args.YearsReport.lower() == "now":
        YearsReport = date.today().year
    else:
        YearsReport = [int(x) for x in args.YearsReport.split(',')]
    
    return Site, DateStart, DateEnd, YearsReport

def Init(Site, DateCheck):
    global Settings
    
    os.chdir(os.path.dirname(os.path.realpath(__file__)))
    
    ReadIni(Site)
    
    Settings['Year'] = DateCheck.strftime('%Y')
    Settings['Month'] = DateCheck.strftime('%m')
    Settings['Day'] = DateCheck.strftime('%d')
    
    #report html folder
    Settings['FolderHTMLReport'] = Settings['FolderHTMLReport'].replace('<YYYY>', Settings['Year']).replace('<MM>', Settings['Month']).replace('<DD>', Settings['Day'])
    if not os.path.exists(Settings['FolderHTMLReport']):
        os.makedirs(Settings['FolderHTMLReport'])
    else:
        filelist = glob(os.path.join(Settings['FolderHTMLReport'], '*'))
        for f in filelist:
            try:
                os.remove(f)
            except:
                pass
    
    InitLogger(os.path.join(Settings['FolderHTMLReport'], 'QClog.txt'))

    #Import config file
    Settings['Config'] = pd.read_csv(Settings['FileConfig'], skiprows=None, header=0, index_col=(0), parse_dates=['ActiveFrom','ActiveTo'], keep_default_na=False, quoting=3)
    #convert datetime into date
    Settings['Config']['ActiveTo'] = Settings['Config'].ActiveTo.dt.date
    Settings['Config']['ActiveFrom'] = Settings['Config'].ActiveFrom.dt.date

def InitLogger(FileLog):
    global logger
    # create formatter
    formatter = logging.Formatter('%(asctime)s> %(message)s')
    
    if 'logger' in globals():
        #close and remove the file handler
        logging.shutdown()
        logger.removeHandler(logger.handlers[1])

    else:
        # create logger
        logger = logging.getLogger()
        logger.handlers.clear() 
        logger.setLevel(VerboseLevel)
        
        # create console handler and set level to debug
        handler_console = logging.StreamHandler()
        handler_console.setLevel(VerboseLevel)
        
        # add formatter to handler
        handler_console.setFormatter(formatter)
        
        # add handler to logger
        logger.addHandler(handler_console)
    
    # create file handler and set level to debug
    handler_file = logging.FileHandler(FileLog, mode='w')
    handler_file.setLevel(VerboseLevel)
    
    # add formatter to handler
    handler_file.setFormatter(formatter)
    
    # add handler to logger
    logger.addHandler(handler_file)

def ReadIni(Site):
    #load daat from the ini file into the variable Settings
    global Settings, INI
    
    #load the ini file if not already laoded
    if not 'INI' in globals():
        INI = configparser.RawConfigParser()
        INI.optionxform = str
        INI.read('checkETC.ini')
    
    #create the Settings dictionary
    Settings = {'Site': Site}
    Settings['FileConfig'] = INI.get(Site, 'FileConfig')
    Settings['FolderHTMLReport'] = INI.get(Site, 'FolderHTMLReport')
    #normally True, False only to save time because this is the slowest part
    Settings['CreateFigures'] = INI.getboolean(Site, 'CreateFigures')
    
#Report functions-----------------------------------------------------------------------------------------------------------------------------------
class ClassReport():
    def __init__(self, ParentFolder, RelativePath, Title, Comment=''):
        #Load model report file
        fid = open('ReportTemplate.html', 'rt')
        self.Model = fid.read()
        fid.close()
        self.ReplaceStringTitle = '***Add title here***'
        self.ReplaceStringBody = '***Add body here***'

        logger.info('Generating report ' + Title + '...')
        
        self.File = os.path.join(ParentFolder, RelativePath)
        self.Link = RelativePath
        
        #find the location of the body
        self.AppendPositionBody = self.Model.find(self.ReplaceStringBody)
        
        #init report with the model
        self.FileContent = self.Model[0:self.AppendPositionBody]
        #replace title
        self.FileContent = self.FileContent.replace(self.ReplaceStringTitle, Title)
        if not Comment:
            self.Append(Comment, True)
        self.Append('Report generated automatically by python script running on computer "' + socket.gethostname() + '". IP: ' + ', '.join(socket.gethostbyname_ex(socket.gethostname())[2]))
        self.Append('Started ' + datetime.utcnow().strftime('%d.%m.%Y %H:%M:%S') + ' local time.')

    def Append(self, Text, CR=True):
        self.FileContent += Text
        if CR:
            self.FileContent += '\r\n'
    
    def AppendLink(self, Link, Text, CR):
        self.Append('<a href="' + Link + '" target="_blank">' + Text + '</a>', CR)
    
    def AppendPopUpLink(self, PreText, Link, Text):
        self.Append('<script language="javascript">' + '\n', False)
        self.Append('var popupWindow = null;' + '\n', False)
        self.Append('function positionedPopup(url,winName,w,h,t,l,scroll){' + '\n', False)
        self.Append('settings =''height=''+h+'',width=''+w+'',top=''+t+'',left=''+l+'',scrollbars=''+scroll+'',resizable''' + '\n', False)
        self.Append('popupWindow = window.open(url,winName,settings)}' + '\n', False)
        self.Append('</script>' + '\n', False)
        self.Append(PreText, False)
        self.Append('<a href="' + Link + '" onclick="positionedPopup(this.href,''myWindow'',''800'',''450'',''100'',''100'',''yes'');return False">' + Text + '</a>', False)
        
    def Terminate(self):
        #write the text in the report file and close it
        
        logger.info('TerminateReport')
        
        self.Append('End ' + datetime.now().strftime('%d/%m/%Y %H:%M:%S') + ' local time')
        
        #write the last part of the html file
        self.Append(self.Model[self.AppendPositionBody + len(self.ReplaceStringBody):], False)
        
        FileId = open(self.File + '_', 'wt')
        if FileId == -1:
            raise Exception(datetime.now().strftime('%d/%m/%Y %H:%M:%S') + '> The file ' + self.File + ' could not be opened')
        
        FileId.write(self.FileContent)
        
        #close the html report file
        FileId.close()
        
        if os.path.exists(self.File):
            os.remove(self.File)
        os.rename(self.File + '_', self.File)
    
#QC tests-------------------------------------------------------------------------------------------------------------------------------------------
def TestHeader(DF, FILE_HEAD_VARS, ColumnsExpected):
    global Settings
    #test the header if there is one
    
    logger.info('TestHeader')
    
    OkHeader = np.nan
    if FILE_HEAD_VARS > 0:
        Report.Append('Check header: ', False)
    
        #check quotes are present
        OkHeader = all([Col[0] == '"' and Col[-1] == '"' for Col in DF.columns])
        Text = ''
        if not OkHeader:
            Text += 'Quotes are missing\n'
        
        #check that column names are the expected ones
        ColumnsFile = [Col.strip('"') for Col in DF.columns]
        OkColumns = [ColumnExpected in ColumnsFile for ColumnExpected in ColumnsExpected]
        OkHeader &= all(OkColumns)
        
        #append report
        if not OkHeader:
            Report.Append('<span style="color: rgb(255,0,0);">', False)
            Report.Append(Text + 'Column names are not the expected ones.', True)
            Report.Append('</span>', False)
        else:
            Report.Append('<span style="color: rgb(0,255,0);">Ok</span>')
            
    return OkHeader

def TestNbColumns(DF):
    global Settings
    
    logger.info('TestNbColumns')
    
    Report.Append('Check number of columns: ', False)
    
    NbChannelsMissing = (DF == '').all().sum()
    NbChannelsExpected = DF.shape[1]
    NbChannelsImported = NbChannelsExpected - NbChannelsMissing
    
    if NbChannelsMissing > 0:
        OkNbColumns = False
        Report.Append('<span style="color: rgb(255,0,0);">', False)
        Report.Append('Found columns: ' + str(NbChannelsImported) + ', expected columns:' + str(NbChannelsExpected), True)
        Report.Append('</span>', False)
    else:
        OkNbColumns = True
        Report.Append('<span style="color: rgb(0,255,0);">Ok</span>')
    
    return OkNbColumns

def TestDates(DF, DateFile, GapAcceptance):
    #check dates
    #DateFile: date inferred from the file name, indicating the timestamp of the last record
    #GapAcceptance in seconds
    global Settings
    
    logger.info('TestDates')
    
    Report.Append('Check dates: ', False)
    
    if len(DF) == 0:
        Report.Append('<span style="color: rgb(255,0,0);">No data</span>')
        Ok = False
    else:
        Report.Append('last record: ' + DF.iat[-1,0].strftime('%d/%m/%Y %H:%M:%S') + ' -> ', False)
        LastGapHour = (DateFile - DF.iat[-1,0].to_pydatetime()).total_seconds()
        if abs(LastGapHour) > GapAcceptance:
            Ok = False
            Report.Append('<span style="color: rgb(255,0,0);">', False)
            Report.Append('last record is %0.2f' % LastGapHour + ' seconds older than the file name date (' + DateFile.strftime('%d/%m/%Y %H:%M:%S'))
            Report.Append('</span>', False)
        else:
            Ok = True
            Report.Append('<span style="color: rgb(0,255,0);">Ok</span>')
    
    return Ok

def TestTimeEC(DF):
    #check milliseconds of timestamps are multiple of 100ms
    global Settings
    
    logger.info('TestDates')
    
    Report.Append('Check times: ', False)
    
    if len(DF) == 0:
        Report.Append('<span style="color: rgb(255,0,0);">No data</span>')
        OkTIMESTAMP = False
    else:
        KoTIMESTAMPs = (DF.TIMESTAMP.astype(np.int64)%100000000) > 0
        OkTIMESTAMP = all(~KoTIMESTAMPs)
        if OkTIMESTAMP:
            Report.Append('<span style="color: rgb(0,255,0);">Ok</span>')
        else:
            FirstWrongTIMESTAMP = DF.TIMESTAMP[KoTIMESTAMPs.index[KoTIMESTAMPs][0]]
            LastWrongTIMESTAMP = DF.TIMESTAMP[KoTIMESTAMPs.index[KoTIMESTAMPs][-1]]
            Report.Append('<span style="color: rgb(255,0,0);">', False)
            Report.Append('Unexpected time stamp from ' + FirstWrongTIMESTAMP.strftime('%d/%m/%Y %H:%M:%S.%f') + ' to ' + LastWrongTIMESTAMP.strftime('%d/%m/%Y %H:%M:%S.%f'))
            Report.Append('</span>', False)
    
    return OkTIMESTAMP

def TestZip(FileZip, FILE_EXTENSION):
    #test that the name in the zip file is correct
    logger.info('TestNbRecords')
    Report.Append('Check file name in the zip file: ', False)
    
    Ok = False
    #unzip
    ZIP = ZipFile(FileZip, 'r')
    CompressedFiles = ZIP.namelist()
    ZIP.close()
    if len(CompressedFiles) == 1:
        Ok = os.path.splitext(os.path.basename(FileZip))[0] + FILE_EXTENSION == CompressedFiles[0]
    
    if Ok:
        Report.Append('<span style="color: rgb(0,255,0);">Ok</span>')
    else:
        Report.Append('<span style="color: rgb(255,0,0);">Files in the zip: ' + ','.join(CompressedFiles) + '</span>')
    
    return Ok

def TestNbRecords(DF, NbExpectedRecords):
    #check the number of records
    global Settings
    
    logger.info('TestNbRecords')
    
    Report.Append('Check number of records: ', False)
    NbRecords = len(DF)
    
    Report.Append(str(NbRecords) + ' -> ', False)
    
    if NbRecords != NbExpectedRecords:
        Ok = False
        Report.Append('<span style="color: rgb(255,0,0);">', False)
        Report.Append(str(100.0*NbRecords/NbExpectedRecords) + ' % of expected records')
        if NbRecords > 0:
            Report.Append('From ' + DF.iat[0,0].strftime('%d/%m/%Y %H:%M:%S') + ' to ' + DF.iat[-1,0].strftime('%d/%m/%Y %H:%M:%S'))
        
        Report.Append('</span>', False)
    else:
        Ok = True
        Report.Append('<span style="color: rgb(0,255,0);">Ok</span>')
    
    return Ok

def TestGaps(DF, Period):
    global Settings
    
    logger.info('TestGaps')
    
    #look for gaps in the date
    Report.Append('Gap detection in the date: ', False)
    if len(DF) == 0:
        Report.Append('<span style="color: rgb(255,0,0);">No data</span>')
    else:
        Period_ms = int(Period * 1000)
        
        RawDateTest = DF.iloc[:,0].diff().astype('timedelta64[ms]') != Period_ms
        NbGap = RawDateTest[1:].values.sum()
        
        if NbGap != 0:
            Ok = False
            MaxDisplayed = 10
            Report.Append('<span style="color: rgb(255,0,0);">', False)
            Report.Append(str(NbGap) + ' gap(s) detected for the periods:')
            
            for i, DateGap in enumerate(DF.iloc[RawDateTest[0:MaxDisplayed].index,0]):
                Report.Append('   ' + DateGap.strftime('%d/%m/%Y %H:%M:%S.%f') + ' > ' + DF.iat[i+1,0].strftime('%d/%m/%Y %H:%M:%S.%f'))                

            if MaxDisplayed < NbGap:
                Report.Append('   ...', False)
            
            Report.Append('</span>', True)
        else:
            Ok = True
            Report.Append('<span style="color: rgb(0,255,0);">Ok</span>')
    
    return Ok

def TestNaN(DF, Header):
    global Settings
    
    logger.info('TestNaN')
    
    #Check for NaN
    Report.Append('Look for NaN: ', False)
    
    Ok = True
    Result = {}
    for Channel, Data in DF.iteritems():
        if Header.at[Channel, 'Process']:
            #compute the nb of nan
            IsNaN = Data.isnull()
            NbNaN = IsNaN.sum()
            if NbNaN > 0:
                Result[Channel] = NbNaN
                Ok = False
        
    if Ok:
        Report.Append('<span style="color: rgb(0,255,0);">Ok</span>')
    else:
        Report.Append('<span style="color: rgb(255,0,0);">', False)
        Report.Append('detected for the following channels:')
        for Channel in Result.keys():
            if Result[Channel] > 0:
                Report.Append('   ' + Channel + ': ' + str(Result[Channel]) + ' (' + str(Result[Channel]*100.0/len(DF)) + '%)')
            
        Report.Append('</span>', False)
    
    return Ok

def TestNum(DF, Header):
    global Settings
    
    logger.info('TestNum')
    
    #Check for out of range values
    Report.Append('Look for non numeric channels: ', False)
    Ok = True
    
    if len(DF) == 0:
        Report.Append('<span style="color: rgb(255,0,0);">No data</span>')
        Ok = False
    else:
        for Channel, Data in DF.iteritems():
            logging.debug(Channel)
            if Header.at[Channel, 'Process']:
                #test min value
                if not pd.api.types.is_numeric_dtype(Data):
                    if Ok:
                        #if first channel with out of range value
                        Report.Append('<span style="color: rgb(255,0,0);">', False)
                        Report.Append('Non numeric channels:', True)
                        Ok = False
                    FirstNonNumericValue = (Data[pd.to_numeric(Data, errors='coerce').isnull()]).iat[0]
                    Report.Append('   ' + Channel + ': ' + FirstNonNumericValue, True)
    
    if Ok == True:
        Report.Append('<span style="color: rgb(0,255,0);">Ok</span>')
    else:
        Report.Append('</span>', False)
    
    return Ok

def TestRange(DF, Header):
    global Settings
    
    logger.info('TestRange')
    
    #Check for out of range values
    Report.Append('Look for out of range values: ', False)
    Ok = True
    NbOutRange = {}
    
    if len(DF) == 0:
        Report.Append('<span style="color: rgb(255,0,0);">No data</span>')
        Ok = False
        for Channel in DF.columns:
            NbOutRange[Channel] = 0
    else:
        for Channel, Data in DF.iteritems():
            logging.debug(Channel)
            if Header.at[Channel, 'Process']:
                #test min value
                if np.isnan(Header.at[Channel, 'Min']):
                    #if the treshold if nan, considers value is in range
                    OutMin = np.zeros(len(Data), dtype=bool) #[False] * len(DF.Channel[Channel]['Data'])
                else:
                    OutMin = Data < Header.at[Channel, 'Min']
                
                #test max value
                if np.isnan(Header.at[Channel, 'Max']):
                    #if the treshold if nan, considers value is in range
                    OutMax = np.zeros(len(Data), dtype=bool)
                else:
                    OutMax = Header.at[Channel, 'Max'] < Data
                OutRange = OutMin | OutMax 
                
                NbOutRange[Channel] = OutRange.sum()
                if NbOutRange[Channel] > 0:
                    if Ok == True:
                        #if first channel with out of range value
                        Report.Append('<span style="color: rgb(255,0,0);">', False)
                        Report.Append('detected for the following channels:', True)
                    
                    Report.Append('   ' + Channel + ': ' + str(NbOutRange[Channel]) + ' (' + str(NbOutRange[Channel]*100.0/len(DF)) + '%)', True)

                    Ok = False
                
            else:
                NbOutRange[Channel] = 0
    
    if Ok == True:
        Report.Append('<span style="color: rgb(0,255,0);">Ok</span>')
    else:
        Report.Append('</span>', False)
    
    return Ok, NbOutRange
    
def TestDiagnosticByte(DF, DiagnosticChannel):
    #DiagnosticChannel = 'Diagnostic Value' #GHG
    #DiagnosticChannel = 'GA_DIAG_CODE' #ETC
    logger.info('TestDiagnosticByte')
    
    #Check the licor diagnostic byte (specific to licor 7200 or 7500)
    #Bits (starting at 1) from 5 to 13 should all be 1 (=True in python)
    BitName = ['AGC0', 'AGC1', 'AGC2', 'AGC3', 'Sync Flag', 'PLL', 'Detector Temperature', 'Chopper Temperature', 'Head Pressure', 'Aux Inputs', 'Inlet T', 'Outlet T', 'Head']
    
    Report.Append('Check the diagnostic byte: ', False)
    Ok = True
    
    if len(DF) == 0:
        Report.Append('<span style="color: rgb(255,0,0);">No data</span>')
        Ok = False
    else:
        if not(DiagnosticChannel in DF.columns):
            Report.Append('<span style="color: rgb(255,0,0);">No Diagnostic Value</span>')
            Ok = False
        else:
            DefaultByte = 0b1111111110000
            ListWithoutNan = DF.loc[:,DiagnosticChannel].copy(deep=True)
            ListWithoutNan.loc[np.isnan(ListWithoutNan)] = DefaultByte
            for NoBit in range(4, 13):
                Bit = bitget_n(ListWithoutNan, NoBit)
            
                if not all(Bit):
                    PositionFirst = Bit.index(False)
                    PositionLast = len(Bit) - 1 - Bit[::-1].index(False)
                    
                    if Ok: #if there was no error so far
                        Report.Append(' ', True)
                        Report.Append('<span style="color: rgb(255,0,0);">', False)

                    Report.AppendPopUpLink('Diagnostic error: ', '../diagnostic_description/description.html', BitName[NoBit])
                    Report.Append('. First error at: ' + DF.TIMESTAMP[PositionFirst].strftime('%d/%m/%Y %H:%M:%S') + '. Last error at: ' + DF.TIMESTAMP[PositionLast].strftime('%d/%m/%Y %H:%M:%S'), True)
                    
                    Ok = False
    
    if Ok == True:
        Report.Append('<span style="color: rgb(0,255,0);">Ok</span>')
    else:
        Report.Append('</span>', False)
    
    return Ok
    
def TestDiagnosticByte2(DF, DiagnosticChannel):
    #DiagnosticChannel = 'Diagnostic Value 2'
    logger.info('TestDiagnosticByte2')
    
    #Check the licor diagnostic byte 2 (specific to licor 7700)
    #should be 1
    
    Report.Append('Check the diagnostic byte 2: ', False)
    Ok = True
    
    if len(DF) == 0:
        Report.Append('<span style="color: rgb(255,0,0);">No data</span>')
        Ok = False
    else:
        if not(DiagnosticChannel in DF.columns):
            Report.Append('<span style="color: rgb(255,0,0);">No Diagnostic Value 2</span>')
            Ok = False
        else:
            Bit = DF.loc[:,DiagnosticChannel].astype(bool).tolist() #converts nan to 1, so it is fine
            if  not all(Bit):
                PositionFirst = Bit.index(False)
                PositionLast = len(Bit) - 1 - Bit[::-1].index(False)
                if Ok: #if there was no error so far
                    Report.Append(' ', True)
                    Report.Append('<span style="color: rgb(255,0,0);">', False)
                PercentageBad = (len(Bit) - sum(Bit)) * 100.0 / len(Bit)
                Report.Append('Diagnostic value 2 (li7700 not synchronised) error (' + str(PercentageBad) + '%). ', False)
                Report.Append('First error at: ' + DF.TIMESTAMP[PositionFirst].strftime('%d/%m/%Y %H:%M:%S') + '. Last error at: ' + DF.TIMESTAMP[PositionLast].strftime('%d/%m/%Y %H:%M:%S'), True)

                Ok = False
    
    
    if Ok == True:
        Report.Append('<span style="color: rgb(0,255,0);">Ok</span>')
    else:
        Report.Append('</span>', False)
    
    return Ok

def TestDiagnosticByteCH4(DF):
    logger.info('TestDiagnosticByteCH4')
    
    #Check the licor CH4 diagnostic byte (specific to licor 7700)
    #Bits (starting at 1) 1 should be 1
    #Bits 2.3.4 should be 1
    #Bits 5-16 should be 0
    
    BitName = ['BOXCONNECTED', 'BADAUXTC3', 'BADAUXTC2', 'BADAUXTC1', 'MOTORFAILURE', 'CALIBRATING', 'BOTTOMHEATERON', 'TOPHEATERON', 'PUMPON', 'MOTORSPINNING', 'BLOCKTEMPUNREGULATED', 'LASERTEMPUNREGULATED', 'BADTEMP', 'REFUNLOCKED', 'NOSIGNAL', 'NOTREADY']
    nan = float('nan')
    BitNominalValue = [True, nan, nan, nan, False, nan, nan, nan, nan, nan, False, False, False, False, False, False] # if nan, the bit is not tested (True=1)
    
    Report.Append('Check the CH4 diagnostic byte: ', False)
    Ok = True
    
    if len(DF) == 0:
        Report.Append('<span style="color: rgb(255,0,0);">No data</span>')
        Ok = False
    else:
        DiagnosticChannel = 'CH4 Diagnostic Value'
        if not (DiagnosticChannel in DF.Channel.keys()):
            Report.Append('<span style="color: rgb(255,0,0);">No Diagnostic Value</span>')
            Ok = False
        else:
            DefaultByte = 0b1
            ListWithoutNan = copy.deepcopy(DF.Channel[DiagnosticChannel]['Data'])
            ListWithoutNan[np.isnan(ListWithoutNan)] = DefaultByte
            ListWithoutNan = ListWithoutNan.astype(int).tolist()
            for NoBit in range(0, 16):
                if not np.isnan(BitNominalValue[NoBit]):
                    Bit = bitget_n(ListWithoutNan, NoBit)
                    Bit = [x == BitNominalValue[NoBit] for x in Bit]
            
            #Bit = [True]*len(DF.Channel[DiagnosticChannel]['Data'])
            #for NoBit in range(0, 16):
            #    if not isnan(BitNominalValue[NoBit]):
            #        for i, x in enumerate(DF.Channel[DiagnosticChannel]['Data']):
            #            if isnan(x):
            #                Bit[i] = True
            #            else:
            #                Bit[i] = bitget(uint16(x), NoBit) == BitNominalValue[NoBit]

                    if not all(Bit):
                        PositionFirst = Bit.index(False)
                        PositionLast = len(Bit) - 1 - Bit[::-1].index(False)
                        if Ok: #if there was no error so far
                            Report.Append(' ', True)
                            Report.Append('<span style="color: rgb(255,0,0);">', False)
                        
                        Report.AppendPopUpLink('Diagnostic error: ', '../diagnostic_description/descriptionCH4.html', BitName[NoBit])
                        PercentageBad = (len(Bit) - sum(Bit)) * 100.0 / len(Bit)
                        Report.Append(' (' + str(PercentageBad) + '%). ', False)
                        Report.Append('First error at: ' + DF.TIMESTAMP[PositionFirst].strftime('%d/%m/%Y %H:%M:%S') + '. Last error at: ' + DF.TIMESTAMP[PositionLast].strftime('%d/%m/%Y %H:%M:%S'), True)

                        Ok = False
    
    
    if Ok == True:
        Report.Append('<span style="color: rgb(0,255,0);">Ok</span>')
    else:
        Report.Append('</span>', False)
    
    return Ok

def bitget_n(byteList, NoBit):
    #bit index strart from 0
    mask = 1<<NoBit
    return [(x&mask)!=0 for x in byteList]
#---------------------------------------------------------------------------------------------------------------------------------------------------

def OutputFigures(DF, Header, NameGroup, BaseName, DateCheck):
    #produce an html file containing figures
    global Settings
    
    Link = ''
    if Settings['CreateFigures']: #normaly True, False only for testing, because this is the slowest part
        logger.info('Create png figures')
        #HTML report object
        ReportFigure = ClassReport(Settings['FolderHTMLReport'], NameGroup + '_' + BaseName + '.html', Settings['Site'] + ' ' + DateCheck.strftime('%Y-%m-%d') + ' ' + NameGroup , 'File ' + BaseName + '. ')
        
        #to not load JS for each figure, but only for the first
        FirstPlot = 'cdn'
        
        Channels = Header.loc[~Header.loc[:,'Group'].isnull(),:].index
        Groups = Header.loc[Channels,'Group']
        
        for Group in pd.unique(Groups):
            #init the figure
            fig = go.Figure()
            PlotMin = True
            PlotMax = True
            for Channel in Channels[Groups==Group]:
                Data = DF.loc[:,Channel]
                logger.info('Generate figure for channel: ' + Channel)
                
                IsNaN = Data.isnull()
                NbNaN = IsNaN.sum()
                NbOk = len(Data) - NbNaN
                
                IsOk = ~ IsNaN
                DateOk = DF.loc[IsOk,'TIMESTAMP']
                DataOk = Data.loc[IsOk]
                
                #plot min & max thresholds if some values are out of range
                [Min, Max] = Header.loc[Channel, ['Min', 'Max']]
                if (not np.isnan(Min)) and PlotMin and any(DataOk<Min):
                    fig.add_trace(go.Scatter(x=DateOk.iloc[[0, -1]], y=[Min,Min], mode='lines', name = 'Min', line=dict(dash='dash')))
                    PlotMin = False
                if (not np.isnan(Max)) and PlotMax and any(DataOk>Max):
                    fig.add_trace(go.Scatter(x=DateOk.iloc[[0, -1]], y=[Max,Max], mode='lines', name = 'Max', line=dict(dash='dash')))
                    PlotMax = False
                
                #plot data
                if len(DataOk) > 0:
                    fig.add_trace(go.Scatter(x=DateOk, y=DataOk, mode='lines', name = Channel))
                
                #plot NaN
                if NbNaN > 0:
                    if NbOk == 0:
                        MeanSingleValue = 0
                    else:
                        #compute average values
                        MeanSingleValue = np.mean(DataOk)
                    
                    DataNaN = [MeanSingleValue]*NbNaN
                    DateNaN = DF.loc[IsNaN,'TIMESTAMP']
                    fig.add_trace(go.Scatter(x=DateNaN, y=DataNaN, mode='markers', name = Channel + 'NaN'))
                    
            fig.update_layout(title=Group)
            FigHtml = fig.to_html(full_html=False, include_plotlyjs=FirstPlot, default_height='40%')
            ReportFigure.Append(FigHtml)
            FirstPlot = False
            Link = ReportFigure.Link
        
        ReportFigure.Terminate()
    return Link

#Main prog------------------------------------------------------------------------------------------------------------------------------------------
if __name__ == "__main__":
    Site, DateStart, DateEnd, YearsReport = GetInputArguments()
    #Site, DateStart, DateEnd, YearsReport = None, None, None, None
    
    if not DateStart is None:
        if DateEnd is None:
            QC(Site, DateStart)
        else:
            QC_n(Site, DateStart, DateEnd)
            
    if not YearsReport is None:
        ListReports(Site,YearsReport)
    
    if (Site is None) and (DateStart is None) and (DateEnd is None) and (YearsReport is None):
        Site = 'GL-ZaF-L'
        QC(Site, date(2022,8,23))
        #QC_n(Site, date(2021,1,1), date(2021,12,31))
        #ListReports(Site,2021)
        
        #QC_n(Site, date(2022,4,26), date(2022,12,31))
        #ListReports(Site,2022)