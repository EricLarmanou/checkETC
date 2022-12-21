# checkETC
Test biomet and eddy covariance data files for ETC format compatiblity and errors

3 main functions are:
- QC: perform tests on 1 specific day
- QC_n: perform tests on a range of dates
- ListReports: build a summary html report of all the controled days
    
it requires:
- an ini file containg general information for each site
```{r, eval = F}
[GL-ZaF]
FolderHTMLReport=O:\Tech_ICOS\DATA\GL-ZaF\3.processed\reports\<YYYY>\<MM>.<DD>
FileConfig=O:\Tech_ICOS\scripts\python\checkETC\checkETC_ZaF.csv
CreateFigures=TRUE
```
Where:
FolderHTMLReport: path of the generated html report files
FileConfig: 

- a config file (csv), with information per data file type (Warning: editing csvl files in excel mess up the double quotes)
- a html template file for the report: ReportEmpty.html
- for each data type, a header file (csv), listing the column names and some criterias
    
todo: add range min and max in figures
      read Input Arguments
      adjust crteria
