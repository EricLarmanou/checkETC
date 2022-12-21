# checkETC
checkETC is a tool for testing biomet and eddy covariance data files for ETC format compatiblity and unrealitic values

The 3 main functions are:
- ```QC(Site, DateCheck = None)```: perform tests on 1 specific day. A html file (Report.html) is produced. A csv file (Flags.csv) is also produced, with one alert flag per file type. Finally for each data file, a html file containg plots is produced (the plot files generation can be diables in the ini file). All the files are generated at the location specified in the config file (see below).
- ```QC_n(Site, DateStart, DateEnd)```: perform a test for each day included between the 2 specified dates
- ```ListReports(Site, Years=None)```: build a summary html report of all the controled days. Generates a html file per year.
    
## Required files:
- an ini file (checkETC.ini) containg general information for each site:
  ```ini
  [GL-ZaF]
  FolderHTMLReport=O:\Tech_ICOS\DATA\GL-ZaF\3.processed\reports\<YYYY>\<MM>.<DD>
  FileConfig=O:\Tech_ICOS\scripts\python\checkETC\checkETC_ZaF.csv
  CreateFigures=TRUE
  ```
  Where:
  - FolderHTMLReport: path of the folder where html report files are generated. If \<YYYY\>, \<MM\>, \<DD\> strings are used, the date of the file being tested is used to build the path
  - FileConfig: path of a csv file listing information for each data file type
  - CreateFigures: bool, to generate or not the plots

- a config file (csv), with information per data file type (Warning: editing csv files in excel mess up the double quotes)


- a html template file for the report: ReportEmpty.html
- for each data type, a header file (csv), listing the column names and some criterias


| Variable | TIMESTAMP | D_SNOW_1_1_1 |
| ------------- | ------------- | ------------- |
| Min | NaN | -0.5 |
| Max | NaN | -2 |
| Process | 0 | 1 |
| Plot | 0 | 1 |

## todo:
- [ ] add range min and max in figures
- [ ] read Input Arguments
- [ ] adjust criteria
      
      
