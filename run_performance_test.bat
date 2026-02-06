@echo off
echo ====================================
echo PACS Performance Monitoring
echo ====================================
echo.
echo This will run the app with detailed logging enabled.
echo Logs will be saved to: logs\performance_TIMESTAMP.log
echo.
echo Instructions:
echo 1. The app will start with monitoring active
echo 2. Open multiple patients (try 3-5 patients)
echo 3. Start downloads for multiple patients
echo 4. Switch between patient tabs
echo 5. Watch the console for performance metrics
echo 6. Close the app when done testing
echo.
echo Press any key to start...
pause >nul

python run_with_logging.py

echo.
echo ====================================
echo Testing complete!
echo Check the logs folder for detailed logs
echo ====================================
pause
