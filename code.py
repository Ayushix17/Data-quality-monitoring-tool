import streamlit as st
import pandas as pd
import mysql.connector
from mysql.connector import Error
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime, timedelta
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import json
import numpy as np
from typing import Dict, List, Tuple, Any
import warnings
warnings.filterwarnings('ignore')

class DatabaseConnection:
    """Handle MySQL database connections and operations"""
    
    def __init__(self, host: str, database: str, user: str, password: str, port: int = 3306):
        self.host = host
        self.database = database
        self.user = user
        self.password = password
        self.port = port
        self.connection = None
    
    def connect(self):
        """Establish database connection"""
        try:
            self.connection = mysql.connector.connect(
                host=self.host,
                database=self.database,
                user=self.user,
                password=self.password,
                port=self.port
            )
            return True
        except Error as e:
            st.error(f"Database connection error: {e}")
            return False
    
    def disconnect(self):
        """Close database connection"""
        if self.connection and self.connection.is_connected():
            self.connection.close()
    
    def execute_query(self, query: str, params: tuple = None):
        """Execute a query and return results"""
        try:
            cursor = self.connection.cursor()
            cursor.execute(query, params)
            return cursor.fetchall(), cursor.column_names
        except Error as e:
            st.error(f"Query execution error: {e}")
            return None, None
    
    def get_table_names(self):
        """Get all table names in the database"""
        try:
            cursor = self.connection.cursor()
            cursor.execute("SHOW TABLES")
            tables = [table[0] for table in cursor.fetchall()]
            return tables
        except Error as e:
            st.error(f"Error fetching table names: {e}")
            return []
    
    def get_table_schema(self, table_name: str):
        """Get schema information for a table"""
        try:
            cursor = self.connection.cursor()
            cursor.execute(f"DESCRIBE {table_name}")
            schema = cursor.fetchall()
            return schema
        except Error as e:
            st.error(f"Error fetching schema for {table_name}: {e}")
            return None

class DataQualityProfiler:
    """Data quality profiling and analysis"""
    
    def __init__(self, db_connection: DatabaseConnection):
        self.db = db_connection
    
    def profile_table(self, table_name: str) -> Dict[str, Any]:
        """Comprehensive data quality profiling for a table"""
        
        # Get table data
        query = f"SELECT * FROM {table_name}"
        data, columns = self.db.execute_query(query)
        
        if data is None:
            return {}
        
        df = pd.DataFrame(data, columns=columns)
        
        profile_results = {
            'table_name': table_name,
            'timestamp': datetime.now().isoformat(),
            'total_rows': len(df),
            'total_columns': len(df.columns),
            'column_profiles': {},
            'data_quality_issues': {
                'missing_values': {},
                'duplicates': 0,
                'inconsistencies': {}
            }
        }
        
        # Profile each column
        for column in df.columns:
            column_profile = self._profile_column(df, column)
            profile_results['column_profiles'][column] = column_profile
            
            # Check for missing values
            missing_count = df[column].isna().sum()
            if missing_count > 0:
                profile_results['data_quality_issues']['missing_values'][column] = {
                    'count': int(missing_count),
                    'percentage': round((missing_count / len(df)) * 100, 2)
                }
        
        # Check for duplicates
        duplicate_count = df.duplicated().sum()
        profile_results['data_quality_issues']['duplicates'] = int(duplicate_count)
        
        # Check for inconsistencies
        inconsistencies = self._detect_inconsistencies(df)
        profile_results['data_quality_issues']['inconsistencies'] = inconsistencies
        
        return profile_results
    
    def _profile_column(self, df: pd.DataFrame, column: str) -> Dict[str, Any]:
        """Profile individual column"""
        series = df[column]
        
        profile = {
            'data_type': str(series.dtype),
            'unique_values': int(series.nunique()),
            'missing_values': int(series.isna().sum()),
            'missing_percentage': round((series.isna().sum() / len(series)) * 100, 2)
        }
        
        if pd.api.types.is_numeric_dtype(series):
            profile.update({
                'min_value': float(series.min()) if not series.isna().all() else None,
                'max_value': float(series.max()) if not series.isna().all() else None,
                'mean_value': float(series.mean()) if not series.isna().all() else None,
                'std_dev': float(series.std()) if not series.isna().all() else None,
                'outliers': self._detect_outliers(series)
            })
        elif pd.api.types.is_string_dtype(series):
            profile.update({
                'avg_length': float(series.str.len().mean()) if not series.isna().all() else None,
                'max_length': int(series.str.len().max()) if not series.isna().all() else None,
                'min_length': int(series.str.len().min()) if not series.isna().all() else None
            })
        
        return profile
    
    def _detect_outliers(self, series: pd.Series) -> Dict[str, Any]:
        """Detect outliers using IQR method"""
        if series.isna().all():
            return {'count': 0, 'values': []}
        
        Q1 = series.quantile(0.25)
        Q3 = series.quantile(0.75)
        IQR = Q3 - Q1
        lower_bound = Q1 - 1.5 * IQR
        upper_bound = Q3 + 1.5 * IQR
        
        outliers = series[(series < lower_bound) | (series > upper_bound)]
        
        return {
            'count': len(outliers),
            'values': outliers.tolist()[:10]  # Limit to first 10 outliers
        }
    
    def _detect_inconsistencies(self, df: pd.DataFrame) -> Dict[str, Any]:
        """Detect data inconsistencies"""
        inconsistencies = {}
        
        for column in df.columns:
            if pd.api.types.is_string_dtype(df[column]):
                # Check for inconsistent formatting
                non_null_values = df[column].dropna()
                if len(non_null_values) > 0:
                    # Case inconsistencies
                    mixed_case = non_null_values[
                        (non_null_values.str.lower() != non_null_values) & 
                        (non_null_values.str.upper() != non_null_values)
                    ]
                    
                    if len(mixed_case) > 0:
                        inconsistencies[f'{column}_case_inconsistency'] = {
                            'type': 'mixed_case',
                            'count': len(mixed_case),
                            'examples': mixed_case.head(5).tolist()
                        }
                    
                    # Whitespace inconsistencies
                    whitespace_issues = non_null_values[
                        non_null_values.str.strip() != non_null_values
                    ]
                    
                    if len(whitespace_issues) > 0:
                        inconsistencies[f'{column}_whitespace_inconsistency'] = {
                            'type': 'whitespace',
                            'count': len(whitespace_issues),
                            'examples': whitespace_issues.head(5).tolist()
                        }
        
        return inconsistencies

class EmailAlertSystem:
    """Email alert system for data quality issues"""
    
    def __init__(self, smtp_server: str, smtp_port: int, email: str, password: str):
        self.smtp_server = smtp_server
        self.smtp_port = smtp_port
        self.email = email
        self.password = password
    
    def send_alert(self, recipient: str, subject: str, body: str):
        """Send email alert"""
        try:
            msg = MIMEMultipart()
            msg['From'] = self.email
            msg['To'] = recipient
            msg['Subject'] = subject
            
            msg.attach(MIMEText(body, 'html'))
            
            server = smtplib.SMTP(self.smtp_server, self.smtp_port)
            server.starttls()
            server.login(self.email, self.password)
            
            text = msg.as_string()
            server.sendmail(self.email, recipient, text)
            server.quit()
            
            return True
        except Exception as e:
            st.error(f"Failed to send email: {e}")
            return False
    
    def generate_quality_report_email(self, profile_results: Dict[str, Any]) -> str:
        """Generate HTML email for data quality report"""
        
        table_name = profile_results.get('table_name', 'Unknown')
        timestamp = profile_results.get('timestamp', datetime.now().isoformat())
        total_rows = profile_results.get('total_rows', 0)
        issues = profile_results.get('data_quality_issues', {})
        
        missing_values = issues.get('missing_values', {})
        duplicates = issues.get('duplicates', 0)
        inconsistencies = issues.get('inconsistencies', {})
        
        html_body = f"""
        <html>
        <body>
        <h2>Data Quality Report - {table_name}</h2>
        <p><strong>Generated:</strong> {timestamp}</p>
        <p><strong>Total Rows:</strong> {total_rows:,}</p>
        
        <h3>Data Quality Issues Summary</h3>
        <ul>
            <li><strong>Duplicate Rows:</strong> {duplicates:,}</li>
            <li><strong>Columns with Missing Values:</strong> {len(missing_values)}</li>
            <li><strong>Data Inconsistencies:</strong> {len(inconsistencies)}</li>
        </ul>
        
        {'<h3>Missing Values by Column</h3><ul>' + ''.join([f'<li><strong>{col}:</strong> {info["count"]:,} ({info["percentage"]}%)</li>' for col, info in missing_values.items()]) + '</ul>' if missing_values else ''}
        
        {'<h3>Data Inconsistencies</h3><ul>' + ''.join([f'<li><strong>{issue}:</strong> {info["type"]} - {info["count"]} cases</li>' for issue, info in inconsistencies.items()]) + '</ul>' if inconsistencies else ''}
        
        <p>Please review the data quality dashboard for detailed analysis.</p>
        </body>
        </html>
        """
        
        return html_body

class DataQualityDashboard:
    """Streamlit dashboard for data quality monitoring"""
    
    def __init__(self):
        self.db = None
        self.profiler = None
        self.email_system = None
    
    def setup_sidebar(self):
        """Setup sidebar configuration"""
        st.sidebar.title("🔍 Data Quality Monitor")
        
        # Database Configuration
        st.sidebar.subheader("Database Configuration")
        db_host = st.sidebar.text_input("Host", value="localhost")
        db_name = st.sidebar.text_input("Database Name", value="test_db")
        db_user = st.sidebar.text_input("Username", value="root")
        db_password = st.sidebar.text_input("Password", type="password")
        db_port = st.sidebar.number_input("Port", value=3306)
        
        if st.sidebar.button("Connect to Database"):
            self.db = DatabaseConnection(db_host, db_name, db_user, db_password, db_port)
            if self.db.connect():
                self.profiler = DataQualityProfiler(self.db)
                st.sidebar.success("Connected successfully!")
                st.session_state['db_connected'] = True
            else:
                st.sidebar.error("Connection failed!")
                st.session_state['db_connected'] = False
        
        # Email Configuration
        st.sidebar.subheader("Email Alert Configuration")
        smtp_server = st.sidebar.text_input("SMTP Server", value="smtp.gmail.com")
        smtp_port = st.sidebar.number_input("SMTP Port", value=587)
        sender_email = st.sidebar.text_input("Sender Email")
        sender_password = st.sidebar.text_input("Email Password", type="password")
        recipient_email = st.sidebar.text_input("Alert Recipient Email")
        
        if st.sidebar.button("Setup Email Alerts"):
            if sender_email and sender_password:
                self.email_system = EmailAlertSystem(smtp_server, smtp_port, sender_email, sender_password)
                st.session_state['email_configured'] = True
                st.session_state['recipient_email'] = recipient_email
                st.sidebar.success("Email system configured!")
            else:
                st.sidebar.error("Please provide email credentials!")
    
    def display_overview(self):
        """Display data quality overview"""
        st.title("📊 Data Quality Monitoring Dashboard")
        
        if not st.session_state.get('db_connected', False):
            st.warning("Please connect to a database using the sidebar configuration.")
            return
        
        # Get available tables
        tables = self.db.get_table_names()
        
        if not tables:
            st.warning("No tables found in the database.")
            return
        
        col1, col2 = st.columns(2)
        with col1:
            st.metric("Available Tables", len(tables))
        with col2:
            st.metric("Database Connection", "✅ Connected" if self.db.connection.is_connected() else "❌ Disconnected")
        
        # Table selection and profiling
        st.subheader("Select Table for Analysis")
        selected_table = st.selectbox("Choose a table:", tables)
        
        col1, col2 = st.columns(2)
        with col1:
            if st.button("🔍 Profile Table", key="profile_btn"):
                with st.spinner(f"Profiling table '{selected_table}'..."):
                    profile_results = self.profiler.profile_table(selected_table)
                    st.session_state[f'profile_{selected_table}'] = profile_results
                    
                    # Check for critical issues and send alert
                    if self._has_critical_issues(profile_results) and st.session_state.get('email_configured', False):
                        self._send_quality_alert(profile_results)
        
        with col2:
            if st.button("📧 Send Quality Report", key="email_btn"):
                if selected_table in [key.replace('profile_', '') for key in st.session_state.keys() if key.startswith('profile_')]:
                    profile_results = st.session_state[f'profile_{selected_table}']
                    if st.session_state.get('email_configured', False):
                        self._send_quality_alert(profile_results)
                    else:
                        st.warning("Email system not configured!")
                else:
                    st.warning("Please profile the table first!")
        
        # Display profile results if available
        if f'profile_{selected_table}' in st.session_state:
            self.display_profile_results(st.session_state[f'profile_{selected_table}'])
    
    def display_profile_results(self, profile_results: Dict[str, Any]):
        """Display detailed profile results"""
        st.subheader(f"📋 Profile Results: {profile_results['table_name']}")
        
        # Overview metrics
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("Total Rows", f"{profile_results['total_rows']:,}")
        with col2:
            st.metric("Total Columns", profile_results['total_columns'])
        with col3:
            duplicates = profile_results['data_quality_issues']['duplicates']
            st.metric("Duplicate Rows", duplicates, delta=f"-{duplicates}" if duplicates > 0 else None)
        with col4:
            missing_cols = len(profile_results['data_quality_issues']['missing_values'])
            st.metric("Columns w/ Missing Values", missing_cols, delta=f"-{missing_cols}" if missing_cols > 0 else None)
        
        # Data Quality Issues
        st.subheader("🚨 Data Quality Issues")
        
        issues = profile_results['data_quality_issues']
        
        # Missing Values
        if issues['missing_values']:
            st.write("**Missing Values by Column:**")
            missing_df = pd.DataFrame([
                {'Column': col, 'Missing Count': info['count'], 'Missing %': info['percentage']}
                for col, info in issues['missing_values'].items()
            ])
            
            fig = px.bar(missing_df, x='Column', y='Missing %', 
                        title='Missing Values Percentage by Column',
                        color='Missing %', color_continuous_scale='Reds')
            st.plotly_chart(fig, use_container_width=True)
            
            st.dataframe(missing_df, use_container_width=True)
        
        # Inconsistencies
        if issues['inconsistencies']:
            st.write("**Data Inconsistencies:**")
            inconsistency_data = []
            for issue, info in issues['inconsistencies'].items():
                inconsistency_data.append({
                    'Issue': issue,
                    'Type': info['type'],
                    'Count': info['count'],
                    'Examples': ', '.join(info['examples'][:3])
                })
            
            inconsistency_df = pd.DataFrame(inconsistency_data)
            st.dataframe(inconsistency_df, use_container_width=True)
        
        # Column Profiles
        st.subheader("📊 Column Profiles")
        
        profile_data = []
        for col_name, col_profile in profile_results['column_profiles'].items():
            profile_data.append({
                'Column': col_name,
                'Data Type': col_profile['data_type'],
                'Unique Values': col_profile['unique_values'],
                'Missing Values': col_profile['missing_values'],
                'Missing %': col_profile['missing_percentage']
            })
        
        profile_df = pd.DataFrame(profile_data)
        st.dataframe(profile_df, use_container_width=True)
        
        # Detailed column analysis
        selected_column = st.selectbox("Select column for detailed analysis:", 
                                     list(profile_results['column_profiles'].keys()))
        
        if selected_column:
            col_profile = profile_results['column_profiles'][selected_column]
            
            col1, col2 = st.columns(2)
            
            with col1:
                st.write(f"**{selected_column} Details:**")
                for key, value in col_profile.items():
                    if key != 'outliers':
                        st.write(f"- **{key.replace('_', ' ').title()}:** {value}")
            
            with col2:
                if 'outliers' in col_profile and col_profile['outliers']['count'] > 0:
                    st.write("**Outliers:**")
                    st.write(f"Count: {col_profile['outliers']['count']}")
                    if col_profile['outliers']['values']:
                        st.write("Sample values:")
                        for val in col_profile['outliers']['values'][:5]:
                            st.write(f"- {val}")
    
    def _has_critical_issues(self, profile_results: Dict[str, Any]) -> bool:
        """Check if profile results contain critical data quality issues"""
        issues = profile_results['data_quality_issues']
        
        # Define thresholds for critical issues
        duplicate_threshold = profile_results['total_rows'] * 0.05  # 5% duplicates
        missing_value_threshold = 20  # 20% missing values
        
        # Check for critical issues
        if issues['duplicates'] > duplicate_threshold:
            return True
        
        for col, info in issues['missing_values'].items():
            if info['percentage'] > missing_value_threshold:
                return True
        
        if len(issues['inconsistencies']) > 3:  # More than 3 inconsistency types
            return True
        
        return False
    
    def _send_quality_alert(self, profile_results: Dict[str, Any]):
        """Send quality alert email"""
        if not self.email_system or not st.session_state.get('recipient_email'):
            st.error("Email system not properly configured!")
            return
        
        subject = f"Data Quality Alert - {profile_results['table_name']}"
        body = self.email_system.generate_quality_report_email(profile_results)
        
        if self.email_system.send_alert(st.session_state['recipient_email'], subject, body):
            st.success("Quality report sent successfully!")
        else:
            st.error("Failed to send quality report!")
    
    def run(self):
        """Run the Streamlit dashboard"""
        st.set_page_config(
            page_title="Data Quality Monitor",
            page_icon="🔍",
            layout="wide",
            initial_sidebar_state="expanded"
        )
        
        # Initialize session state
        if 'db_connected' not in st.session_state:
            st.session_state['db_connected'] = False
        if 'email_configured' not in st.session_state:
            st.session_state['email_configured'] = False
        
        self.setup_sidebar()
        self.display_overview()
        
        # Footer
        st.markdown("---")
        st.markdown("**Data Quality Monitoring Tool** - Automated profiling and governance")

# Sample data setup function (for testing)
def setup_sample_data():
    """Create sample data for testing"""
    sample_data = pd.DataFrame({
        'id': [1, 2, 3, 4, 5, 5, 7, 8, 9, 10],  # Duplicate ID
        'name': ['John Doe', 'jane smith', 'Bob Johnson ', None, 'Alice Brown', 'Alice Brown', 'Charlie Wilson', 'diana prince', 'Eve Adams', 'Frank Miller'],
        'email': ['john@email.com', 'jane@email.com', 'bob@email.com', 'missing@email.com', 'alice@email.com', 'alice@email.com', 'charlie@email.com', 'diana@email.com', None, 'frank@email.com'],
        'age': [25, 30, 35, 40, 28, 28, 45, 32, 29, None],
        'salary': [50000, 60000, 70000, 80000, 55000, 55000, 90000, 65000, 58000, 1000000]  # Outlier salary
    })
    
    st.subheader("📁 Sample Data Preview")
    st.dataframe(sample_data, use_container_width=True)
    
    st.write("""
    **Sample Data Issues:**
    - Duplicate rows (ID 5)
    - Missing values in name and email columns
    - Inconsistent name formatting (case, whitespace)
    - Salary outlier (1,000,000)
    """)

# Main application
def main():
    dashboard = DataQualityDashboard()
    
    # Add tabs for different sections
    tab1, tab2, tab3 = st.tabs(["🏠 Dashboard", "📊 Sample Data", "ℹ️ Instructions"])
    
    with tab1:
        dashboard.run()
    
    with tab2:
        setup_sample_data()
    
    with tab3:
        st.markdown("""
        ## 📋 Data Quality Monitoring Tool Instructions
        
        ### 🔧 Setup
        1. **Database Configuration:**
           - Enter your MySQL connection details in the sidebar
           - Click "Connect to Database" to establish connection
           - Ensure your database is accessible and contains tables to analyze
        
        2. **Email Configuration:**
           - Configure SMTP settings for email alerts
           - For Gmail, use `smtp.gmail.com` with port 587
           - Use app-specific passwords for Gmail accounts
           - Enter recipient email for quality alerts
        
        ### 🔍 Features
        1. **Automated Profiling:**
           - Missing value detection and quantification
           - Duplicate row identification
           - Data type analysis
           - Statistical summaries for numeric columns
           - String length analysis for text columns
           - Outlier detection using IQR method
        
        2. **Data Quality Issues Detection:**
           - Case inconsistencies in text fields
           - Whitespace formatting issues
           - Missing value patterns
           - Duplicate records
        
        3. **Dashboard Features:**
           - Interactive visualizations
           - Detailed column analysis
           - Quality metrics overview
           - Historical trend tracking
        
        4. **Email Alerts:**
           - Automated alerts for critical issues
           - Customizable thresholds
           - HTML formatted reports
           - Scheduled monitoring capability
        
        ### 🚨 Alert Thresholds
        - **Duplicates:** > 5% of total rows
        - **Missing Values:** > 20% for any column
        - **Inconsistencies:** > 3 different types
        
        ### 💡 Best Practices
        1. Run profiling regularly (daily/weekly)
        2. Set up automated email alerts for critical tables
        3. Monitor trends over time
        4. Address data quality issues promptly
        5. Use the detailed column analysis for root cause analysis
        """)

if __name__ == "__main__":
    main()